// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Waves contributors
#pragma once

#include "lite.h"
#include "session_observer.h"
#include <limits>

namespace waves_lite_session {

struct BoundedBody {
    std::string bytes;
    bool failed = false;
};

inline size_t receive_body(char* data, size_t size, size_t count, void* context) {
    BoundedBody& body = *static_cast<BoundedBody*>(context);
    if (!size || !count) return 0;
    if ((size && count > std::numeric_limits<size_t>::max() / size) ||
        size * count > kBodyLimit - body.bytes.size()) {
        body.failed = true;
        return 0;
    }
    try {
        body.bytes.append(data, size * count);
        return size * count;
    } catch (...) {
        body.failed = true;
        return 0;
    }
}

inline UpstreamResponse request_storefront(const std::string& persisted_developer, const std::string& music,
        const std::function<std::string()>& developer_source) {
    UpstreamResponse response;
    response.transport_ok = false;
    if (!header_valid(persisted_developer) || !header_valid(music)) return response;
    // Native developer tokens expire independently of the cached account token.
    // Only the live request below establishes authentication. The persisted
    // context stays intact while the isolated source supplies a fresh token.
    const std::string developer = developer_source();
    if (!header_valid(developer)) return response;
    CurlEasy curl;
    if (!curl.ok) return response;
    CurlSlist headers;
    if (!headers.append(("Authorization: Bearer " + developer).c_str()) ||
        !headers.append(("Music-User-Token: " + music).c_str()) ||
        !headers.append("Accept: application/json")) return response;
    BoundedBody body;
    // These two options are absent from the checked minimal libcurl declarations.
    const int proxy = 10004, no_proxy = 10177;
    if (!curl.setOptStr(CURLOPT_URL, "https://api.music.apple.com/v1/me/storefront") ||
        !curl.setOptStr(proxy, "") || !curl.setOptStr(no_proxy, "*") ||
        !curl.setOptInt(CURLOPT_SSL_VERIFYPEER, 1L) || !curl.setOptInt(CURLOPT_SSL_VERIFYHOST, 2L) ||
        !curl.setOptInt(CURLOPT_FOLLOWLOCATION, 0L) || !curl.setOptInt(CURLOPT_MAXREDIRS, 0L) ||
        !curl.setOptInt(CURLOPT_PROTOCOLS, CURLPROTO_HTTPS) ||
        !curl.setOptInt(CURLOPT_REDIR_PROTOCOLS, CURLPROTO_HTTPS) ||
        !curl.setOptInt(CURLOPT_TIMEOUT_MS, 5000L) || !curl.setOptInt(CURLOPT_CONNECTTIMEOUT_MS, 2000L) ||
        !curl.setOptStr(CURLOPT_ACCEPT_ENCODING, "identity") ||
        !curl.setOptPtr(CURLOPT_HTTPHEADER, headers.list) ||
        !curl.setOptPtr(CURLOPT_WRITEFUNCTION, reinterpret_cast<void*>(&receive_body)) ||
        !curl.setOptPtr(CURLOPT_WRITEDATA, &body) || !curl.perform() || body.failed) return response;
    response.status = curl.getResponseCode();
    response.transport_ok = curl.ok && response.status > 0;
    response.body = std::move(body.bytes);
    return response;
}

} // namespace waves_lite_session
