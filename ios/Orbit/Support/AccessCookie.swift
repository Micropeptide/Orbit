import Foundation

/// A web view cannot be made to send the Cloudflare Access service token on every call a page makes, and Cloudflare sets no
/// cookie for a service token. It does accept its own signed token as the `CF_Authorization` cookie, and the Mac hands back the
/// one this phone's request arrived with. So before a page loads, this fetches it over the (signed) API and returns it as a
/// cookie to put in the web view's store. For a Mac reached any other way there is nothing to do and it returns nil.
enum AccessCookie {
    static func fetch(pairing: Pairing?) async -> HTTPCookie? {
        guard let pairing, let base = pairing.base else { return nil }
        let extra = pairing.accessHeaders(for: base)
        guard !extra.isEmpty, let url = URL(string: "/api/access/cookie", relativeTo: base) else { return nil }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.setValue("Bearer \(pairing.token)", forHTTPHeaderField: "Authorization")
        for (k, v) in extra { req.setValue(v, forHTTPHeaderField: k) }
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let jwt = obj["jwt"] as? String, !jwt.isEmpty,
              let host = obj["host"] as? String, host == base.host else { return nil }
        var props: [HTTPCookiePropertyKey: Any] = [
            .name: "CF_Authorization", .value: jwt, .path: "/", .domain: host,
            .secure: "TRUE", HTTPCookiePropertyKey("HttpOnly"): "TRUE",
        ]
        if let exp = (obj["exp"] as? NSNumber)?.doubleValue, exp > 0 { props[.expires] = Date(timeIntervalSince1970: exp) }
        return HTTPCookie(properties: props)
    }
}
