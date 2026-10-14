import Foundation
import UserNotifications

/// What a chat keeps working toward across answers. The Mac drives it: after each
/// answer it checks the work against the objective and carries on, or stops and says
/// why (done, stuck, over budget, out of turns, stopped by you). The phone shows where
/// it stands and offers the same controls as the Mac.
struct Goal: Codable, Hashable, Equatable {
    var objective: String
    var status: String            // active | paused | blocked | budget | complete
    var token_budget: Int
    var tokens_used: Int
    var max_turns: Int
    var turns_used: Int
    var reason: String
    var note: String
    /// What each check said, and each stop and start, oldest first.
    var history: [Entry]

    struct Entry: Codable, Hashable {
        var t: Double
        var verdict: String
        var reason: String
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            t = c.lenientDouble(.t) ?? 0
            verdict = c.lenientString(.verdict) ?? ""
            reason = c.lenientString(.reason) ?? ""
        }
        enum CodingKeys: String, CodingKey { case t, verdict, reason }
    }

    enum CodingKeys: String, CodingKey {
        case objective, status, token_budget, tokens_used, max_turns, turns_used, reason, note, history
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        objective = c.lenientString(.objective) ?? ""
        status = c.lenientString(.status) ?? "paused"
        token_budget = Int(c.lenientDouble(.token_budget) ?? 0)
        tokens_used = Int(c.lenientDouble(.tokens_used) ?? 0)
        max_turns = Int(c.lenientDouble(.max_turns) ?? 20)
        turns_used = Int(c.lenientDouble(.turns_used) ?? 0)
        reason = c.lenientString(.reason) ?? ""
        note = c.lenientString(.note) ?? ""
        history = (try? c.decode([Entry].self, forKey: .history)) ?? []
    }

    init?(_ d: [String: Any]?) {
        guard let d, let data = try? JSONSerialization.data(withJSONObject: d),
              let g = try? JSONDecoder().decode(Goal.self, from: data) else { return nil }
        self = g
    }

    /// In words, as the strip shows it.
    var word: String {
        switch status {
        case "active": return "working toward"
        case "paused": return "paused"
        case "blocked": return "needs you"
        case "budget": return "over budget"
        case "complete": return "done"
        default: return status
        }
    }

    var usage: String {
        var bits = ["\(turns_used)/\(max_turns) turns"]
        if token_budget > 0 {
            bits.append("\(tokens_used.formatted())/\(token_budget.formatted()) tokens")
        } else if tokens_used > 0 {
            bits.append("\(tokens_used.formatted()) tokens")
        }
        return bits.joined(separator: " · ")
    }

    var overBudget: Bool { token_budget > 0 && tokens_used >= token_budget }
}

/// An answer left work undone: the Mac offers to keep going until it is done, and takes
/// the offer on its own when `deadline` passes unless you answer.
struct GoalOffer: Hashable, Codable {
    var id: String
    var objective: String
    var why: String
    var deadline: Date?

    enum CodingKeys: String, CodingKey { case id, objective, why, remaining }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        objective = c.lenientString(.objective) ?? ""
        why = c.lenientString(.why) ?? ""
        deadline = c.lenientDouble(.remaining).map { Date().addingTimeInterval($0) }
    }

    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id); try c.encode(objective, forKey: .objective); try c.encode(why, forKey: .why)
    }

    init?(_ d: [String: Any]?) {
        guard let d, let id = d["id"] as? String else { return nil }
        self.id = id
        objective = (d["objective"] as? String) ?? ""
        why = (d["why"] as? String) ?? ""
        let left = (d["remaining"] as? Double) ?? (d["remaining"] as? Int).map(Double.init)
        deadline = left.map { Date().addingTimeInterval($0) }
    }
}

extension OrbitServer {
    /// `/api/goal`: get | set | edit | pause | resume | clear. Returns the goal as it now
    /// stands, and whether a resume started the next answer.
    func goal(_ sid: String, op: String, objective: String? = nil, tokenBudget: Int? = nil,
              maxTurns: Int? = nil) async throws -> (goal: Goal?, started: Bool) {
        var body: [String: Any] = ["sid": sid, "op": op]
        if let objective { body["objective"] = objective }
        if let tokenBudget { body["token_budget"] = tokenBudget }
        if let maxTurns { body["max_turns"] = maxTurns }
        let obj = try await postJSON("/api/goal", body)
        return (Goal(obj["goal"] as? [String: Any]), (obj["started"] as? Bool) ?? false)
    }
}

extension AppState {
    /// Read the open chat's goal again -- after an answer, when the Mac has checked it.
    func refreshGoal(_ sid: String) async {
        guard let server, let r = try? await server.goal(sid, op: "get") else { return }
        if openChat?.sid == sid { goal = r.goal }
    }

    /// After an answer in a chat with an active goal the Mac checks the work, which
    /// takes a few seconds and can end in a verdict that changes nothing else on screen:
    /// keep asking until it settles, or the next answer it starts takes over.
    func followGoal(_ sid: String) {
        guard goal?.status == "active" else { return }
        Task {
            for _ in 0..<20 {
                try? await Task.sleep(for: .seconds(3))
                guard openChat?.sid == sid else { return }
                await refreshGoal(sid)
                guard goal?.status == "active", !runningChats.contains(sid), !streaming else { return }
            }
        }
    }

    /// Yes or no to the offer to keep going. A yes starts the next answer at once.
    func answerGoalOffer(sid: String, accept: Bool) async {
        for _ in 0..<40 where server == nil { try? await Task.sleep(for: .milliseconds(100)) }
        guard let server else { return }
        if openChat?.sid == sid { goalOffer = nil }
        do {
            let r = try await server.goal(sid, op: accept ? "accept" : "decline")
            if openChat?.sid == sid { goal = r.goal }
            if r.started {
                toast("Carrying on toward the goal")
                if openChat?.sid == sid { try? await Task.sleep(for: .milliseconds(700)); await open(sid) }
            }
        } catch {
            toast(error.localizedDescription)
        }
        clearGoalOfferNotification(sid)
    }

    /// The offer, on the Lock Screen when you are not looking: Keep going / No thanks.
    func notifyGoalOffer(_ o: GoalOffer, sid: String) {
        guard backgrounded else { return }
        let c = UNMutableNotificationContent()
        c.title = "Keep going until it's done?"
        var body = o.why.prefix(1).uppercased() + o.why.dropFirst()
        if let dl = o.deadline {
            body += " — it carries on by itself at " + dl.formatted(date: .omitted, time: .shortened) + " unless you say no"
        }
        c.body = AppState.lockScreen(String(body.prefix(240)), otherwise: "A chat has work left. Open Orbit.")
        c.sound = .default
        c.categoryIdentifier = Notifications.offerCategory
        c.userInfo = ["sid": sid]
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: "goaloffer-" + sid, content: c, trigger: nil))
    }

    func clearGoalOfferNotification(_ sid: String) {
        UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: ["goaloffer-" + sid])
    }

    func goalAction(_ op: String, objective: String? = nil, tokenBudget: Int? = nil,
                    maxTurns: Int? = nil) async {
        guard let server, let sid = openChat?.sid else { return }
        do {
            let r = try await server.goal(sid, op: op, objective: objective,
                                          tokenBudget: tokenBudget, maxTurns: maxTurns)
            goal = r.goal
            if r.started {
                toast("Carrying on toward the goal")
                try? await Task.sleep(for: .milliseconds(700))
                await open(sid)                 // joins the answer it just started
            }
            await loadChats()
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// Send this message as the chat's goal: it keeps working until the Mac judges it done.
    func sendGoal(_ text: String) async {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { showGoalEditor = true; return }
        await send(t, goal: true)
    }
}


/// A chat this one started, messaged, or works for, with what it is doing now.
struct ChatLink: Identifiable, Hashable {
    var sid: String
    var title: String
    var role: String
    var state: String
    var goal: String?
    var id: String { sid }

    init?(_ d: [String: Any]) {
        guard let sid = d["sid"] as? String else { return nil }
        self.sid = sid
        title = (d["title"] as? String) ?? sid
        role = (d["role"] as? String) ?? ""
        state = (d["state"] as? String) ?? ""
        goal = d["goal"] as? String
    }
}

extension OrbitServer {
    /// `/api/links`: the chats a chat talks to, whom it waits on now, and its goal.
    func links(_ sid: String) async throws -> (links: [ChatLink], talkingTo: String?, goal: Goal?) {
        let obj = try await getJSON("/api/links?sid=\(Self.escaped(sid))") as? [String: Any] ?? [:]
        let links = ((obj["links"] as? [[String: Any]]) ?? []).compactMap(ChatLink.init)
        let talking = (obj["talking_to"] as? [String: Any])?["title"] as? String
        return (links, talking, Goal(obj["goal"] as? [String: Any]))
    }
}
