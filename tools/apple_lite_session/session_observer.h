// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Waves contributors
#pragma once

#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <fcntl.h>
#include <functional>
#include <limits>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>
#ifdef __linux__
#include <sys/inotify.h>
#endif

namespace waves_lite_session {

const size_t kBodyLimit = 65536;
const size_t kTokenLimit = 8192;
const uint64_t kCounterLimit = 9007199254740991ULL;

enum class Error {
    None, CredentialsUnavailable, CredentialContextChanged, ObserverBusy,
    UpstreamUnavailable, UpstreamRejected, InvalidUpstreamResponse, ObserverUnavailable
};

inline const char* error_name(Error error) {
    switch (error) {
        case Error::None: return "";
        case Error::CredentialsUnavailable: return "credentials_unavailable";
        case Error::CredentialContextChanged: return "credential_context_changed";
        case Error::ObserverBusy: return "observer_busy";
        case Error::UpstreamUnavailable: return "upstream_unavailable";
        case Error::UpstreamRejected: return "upstream_rejected";
        case Error::InvalidUpstreamResponse: return "invalid_upstream_response";
        case Error::ObserverUnavailable: return "observer_unavailable";
    }
    return "observer_unavailable";
}

struct Observation {
    bool authenticated = false;
    std::string storefront;
    std::string session_revision;
    Error error = Error::ObserverUnavailable;
    std::string json() const {
        return std::string("{\"protocol\":\"waves-lite-session-v1\",\"authenticated\":") +
            (authenticated ? "true" : "null") + ",\"storefront\":\"" + storefront +
            "\",\"account_id\":\"\",\"session_revision\":\"" + session_revision +
            "\",\"error\":\"" + error_name(error) + "\"}";
    }
};

struct CachedCredentials {
    std::string dev_token, music_token, storefront;
    uint64_t generation = 0;
    bool operator==(const CachedCredentials& other) const {
        return dev_token == other.dev_token && music_token == other.music_token &&
            storefront == other.storefront && generation == other.generation;
    }
};

struct UpstreamResponse {
    bool transport_ok = true;
    long status = 0;
    std::string body;
};

inline bool region_valid(const std::string& value) {
    return value.size() == 2 && value[0] >= 'a' && value[0] <= 'z' && value[1] >= 'a' && value[1] <= 'z';
}

inline bool header_valid(const std::string& value) {
    if (value.empty() || value.size() > kTokenLimit) return false;
    for (unsigned char character : value) if (character < 33 || character > 126) return false;
    return true;
}

inline bool os_random(unsigned char* output, size_t count) {
    const int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return false;
    size_t offset = 0;
    while (offset < count) {
        const ssize_t amount = read(fd, output + offset, count - offset);
        if (amount < 0 && errno == EINTR) continue;
        if (amount <= 0) break;
        offset += static_cast<size_t>(amount);
    }
    const bool closed = close(fd) == 0;
    return offset == count && closed;
}

namespace detail {

struct JsonValue {
    enum Kind { Other, String, Object, Array } kind = Other;
    std::string text;
    std::map<std::string, JsonValue> fields;
    std::vector<JsonValue> items;
};

// Parse the whole bounded document. Duplicate fields and excessive depth are
// rejected before the response can be classified as authentication evidence.
class JsonParser {
public:
    explicit JsonParser(const std::string& source) : source_(source) {}
    bool parse(JsonValue& value) {
        return source_.size() <= kBodyLimit && read_value(value, 0) && whitespace() == source_.size();
    }
private:
    size_t whitespace() {
        while (offset_ < source_.size() && (source_[offset_] == ' ' || source_[offset_] == '\t' ||
               source_[offset_] == '\r' || source_[offset_] == '\n')) ++offset_;
        return offset_;
    }
    bool consume(char character) {
        whitespace();
        if (offset_ == source_.size() || source_[offset_] != character) return false;
        ++offset_;
        return true;
    }
    bool read_hex(unsigned int& code) {
        code = 0;
        for (int i = 0; i < 4; ++i) {
            if (offset_ == source_.size()) return false;
            const char digit = source_[offset_++];
            code *= 16;
            if (digit >= '0' && digit <= '9') code += digit - '0';
            else if (digit >= 'a' && digit <= 'f') code += digit - 'a' + 10;
            else if (digit >= 'A' && digit <= 'F') code += digit - 'A' + 10;
            else return false;
        }
        return true;
    }
    static void append_unicode(std::string& text, unsigned int code) {
        if (code < 128) text += static_cast<char>(code);
        else if (code < 2048) {
            text += static_cast<char>(0xc0 | (code >> 6));
            text += static_cast<char>(0x80 | (code & 63));
        } else if (code < 65536) {
            text += static_cast<char>(0xe0 | (code >> 12));
            text += static_cast<char>(0x80 | ((code >> 6) & 63));
            text += static_cast<char>(0x80 | (code & 63));
        } else {
            text += static_cast<char>(0xf0 | (code >> 18));
            text += static_cast<char>(0x80 | ((code >> 12) & 63));
            text += static_cast<char>(0x80 | ((code >> 6) & 63));
            text += static_cast<char>(0x80 | (code & 63));
        }
    }
    bool read_string(std::string& text) {
        if (!consume('"')) return false;
        while (offset_ < source_.size()) {
            const unsigned char character = source_[offset_++];
            if (character == '"') return true;
            if (character < 32) return false;
            if (character >= 128) {
                unsigned int code = 0;
                size_t continuation = 0;
                unsigned int minimum = 0;
                if (character >= 0xc2 && character <= 0xdf) { code = character & 31; continuation = 1; minimum = 128; }
                else if (character >= 0xe0 && character <= 0xef) { code = character & 15; continuation = 2; minimum = 2048; }
                else if (character >= 0xf0 && character <= 0xf4) { code = character & 7; continuation = 3; minimum = 65536; }
                else return false;
                for (size_t i = 0; i < continuation; ++i) {
                    if (offset_ == source_.size()) return false;
                    const unsigned char next = source_[offset_++];
                    if (next < 0x80 || next > 0xbf) return false;
                    code = (code << 6) | (next & 63);
                }
                if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return false;
                append_unicode(text, code);
                continue;
            }
            if (character != '\\') { text += static_cast<char>(character); continue; }
            if (offset_ == source_.size()) return false;
            const char escaped = source_[offset_++];
            if (escaped == '"' || escaped == '\\' || escaped == '/') text += escaped;
            else if (escaped == 'b') text += '\b';
            else if (escaped == 'f') text += '\f';
            else if (escaped == 'n') text += '\n';
            else if (escaped == 'r') text += '\r';
            else if (escaped == 't') text += '\t';
            else if (escaped == 'u') {
                unsigned int code = 0;
                if (!read_hex(code)) return false;
                if (code >= 0xd800 && code <= 0xdbff) {
                    if (offset_ + 2 > source_.size() || source_[offset_] != '\\' || source_[offset_ + 1] != 'u') return false;
                    offset_ += 2;
                    unsigned int low = 0;
                    if (!read_hex(low) || low < 0xdc00 || low > 0xdfff) return false;
                    code = 0x10000 + ((code - 0xd800) << 10) + (low - 0xdc00);
                } else if (code >= 0xdc00 && code <= 0xdfff) {
                    return false;
                }
                append_unicode(text, code);
            } else return false;
        }
        return false;
    }
    bool read_value(JsonValue& value, size_t depth) {
        if (depth > 16 || ++values_ > 4096 || whitespace() == source_.size()) return false;
        const char first = source_[offset_];
        if (first == '"') { value.kind = JsonValue::String; return read_string(value.text); }
        if (first == '{') {
            value.kind = JsonValue::Object;
            ++offset_;
            if (consume('}')) return true;
            do {
                std::string name;
                JsonValue child;
                if (!read_string(name) || value.fields.count(name) || !consume(':') || !read_value(child, depth + 1)) return false;
                value.fields.emplace(name, std::move(child));
                if (consume('}')) return true;
            } while (consume(','));
            return false;
        }
        if (first == '[') {
            value.kind = JsonValue::Array;
            ++offset_;
            if (consume(']')) return true;
            do {
                JsonValue child;
                if (!read_value(child, depth + 1)) return false;
                value.items.push_back(std::move(child));
                if (consume(']')) return true;
            } while (consume(','));
            return false;
        }
        const size_t start = offset_;
        while (offset_ < source_.size() && source_[offset_] != ',' && source_[offset_] != ']' && source_[offset_] != '}' &&
               source_[offset_] != ' ' && source_[offset_] != '\t' && source_[offset_] != '\r' && source_[offset_] != '\n') ++offset_;
        const std::string literal = source_.substr(start, offset_ - start);
        if (literal == "null" || literal == "true" || literal == "false") return true;
        size_t index = literal[0] == '-' ? 1 : 0;
        if (index == literal.size()) return false;
        if (literal[index] == '0') ++index;
        else {
            if (literal[index] < '1' || literal[index] > '9') return false;
            while (index < literal.size() && literal[index] >= '0' && literal[index] <= '9') ++index;
        }
        if (index < literal.size() && literal[index] == '.') {
            const size_t digits = ++index;
            while (index < literal.size() && literal[index] >= '0' && literal[index] <= '9') ++index;
            if (index == digits) return false;
        }
        if (index < literal.size() && (literal[index] == 'e' || literal[index] == 'E')) {
            ++index;
            if (index < literal.size() && (literal[index] == '+' || literal[index] == '-')) ++index;
            const size_t digits = index;
            while (index < literal.size() && literal[index] >= '0' && literal[index] <= '9') ++index;
            if (index == digits) return false;
        }
        return index == literal.size();
    }
    const std::string& source_;
    size_t offset_ = 0, values_ = 0;
};

inline bool storefront_response(const std::string& body, std::string& storefront) {
    JsonValue root;
    if (!JsonParser(body).parse(root) || root.kind != JsonValue::Object || root.fields.count("errors")) return false;
    const std::map<std::string, JsonValue>::const_iterator data = root.fields.find("data");
    if (data == root.fields.end() || data->second.kind != JsonValue::Array || data->second.items.size() != 1) return false;
    const JsonValue& item = data->second.items[0];
    if (item.kind != JsonValue::Object) return false;
    const std::map<std::string, JsonValue>::const_iterator id = item.fields.find("id"), type = item.fields.find("type");
    if (id == item.fields.end() || type == item.fields.end() || id->second.kind != JsonValue::String ||
        type->second.kind != JsonValue::String || type->second.text != "storefronts" || !region_valid(id->second.text)) return false;
    storefront = id->second.text;
    return true;
}

inline std::string version(const struct stat& info) {
    std::ostringstream value;
    value << info.st_dev << ':' << info.st_ino << ':' << info.st_mode << ':' << info.st_uid << ':' << info.st_size;
#ifdef __APPLE__
    value << ':' << info.st_mtimespec.tv_sec << ':' << info.st_mtimespec.tv_nsec << ':' << info.st_ctimespec.tv_sec << ':' << info.st_ctimespec.tv_nsec;
#else
    value << ':' << info.st_mtim.tv_sec << ':' << info.st_mtim.tv_nsec << ':' << info.st_ctim.tv_sec << ':' << info.st_ctim.tv_nsec;
#endif
    return value.str();
}

inline std::string directory_version(const struct stat& info) {
#ifdef __linux__
    // inotify records directory metadata and credential-file ABA changes.
    // Unrelated SDK storage must not change this credential witness.
    std::ostringstream value;
    value << info.st_dev << ':' << info.st_ino << ':' << info.st_mode << ':' << info.st_uid;
    return value.str();
#else
    return version(info);
#endif
}

const char* const kCredentialFileNames[] = {"DEV_TOKEN", "MUSIC_TOKEN", "STOREFRONT_ID"};

struct Files {
    bool valid = false;
    std::string dev_token, music_token, storefront, versions;
};

inline Files read_files(const std::string& directory) {
    Files files;
    const int dir = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (dir < 0) return files;
    struct stat owner;
    bool valid = fstat(dir, &owner) == 0 && S_ISDIR(owner.st_mode) && owner.st_uid == geteuid() && (owner.st_mode & 0777) == 0700;
    if (valid) files.versions = directory_version(owner);
    std::string* values[] = {&files.dev_token, &files.music_token, &files.storefront};
    for (size_t i = 0; valid && i < 3; ++i) {
        const int fd = openat(dir, kCredentialFileNames[i], O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
        struct stat before, after;
        valid = fd >= 0 && fstat(fd, &before) == 0 && S_ISREG(before.st_mode) && before.st_uid == geteuid() &&
            (before.st_mode & 0777) == 0600 && before.st_nlink == 1 && before.st_size > 0 && before.st_size <= static_cast<off_t>(kTokenLimit);
        char data[1024];
        while (valid) {
            const ssize_t amount = read(fd, data, sizeof(data));
            if (amount < 0 && errno == EINTR) continue;
            if (amount < 0) { valid = false; break; }
            if (amount == 0) break;
            values[i]->append(data, static_cast<size_t>(amount));
            if (values[i]->size() > kTokenLimit) valid = false;
        }
        if (valid) valid = fstat(fd, &after) == 0 && version(before) == version(after);
        if (valid) files.versions += "/" + version(after);
        if (fd >= 0 && close(fd) != 0) valid = false;
        while (!values[i]->empty() && (values[i]->back() == '\r' || values[i]->back() == '\n' || values[i]->back() == ' ')) values[i]->pop_back();
    }
    struct stat after;
    if (valid) valid = fstat(dir, &after) == 0 && directory_version(owner) == directory_version(after);
    if (close(dir) != 0) valid = false;
    files.valid = valid;
    return files;
}

// Linux filesystem events catch replacement followed by restoration of the
// same inode/bytes during an upstream request. Overflow is a failed observation.
class DirectoryEvents {
public:
    ~DirectoryEvents() {
#ifdef __linux__
        if (fd_ >= 0) close(fd_);
#endif
    }
    bool start(const std::string& directory) {
#ifdef __linux__
        if (directory == directory_ && fd_ >= 0) return true;
        if (fd_ >= 0) close(fd_);
        fd_ = inotify_init1(IN_CLOEXEC | IN_NONBLOCK);
        if (fd_ < 0) return false;
        const uint32_t events = IN_CLOSE_WRITE | IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO | IN_ATTRIB | IN_DELETE_SELF | IN_MOVE_SELF;
        if (inotify_add_watch(fd_, directory.c_str(), events | IN_ONLYDIR | IN_DONT_FOLLOW) < 0) {
            close(fd_);
            fd_ = -1;
            directory_.clear();
            return false;
        }
        directory_ = directory;
#else
        (void)directory;
#endif
        return true;
    }
    bool changed(bool& unavailable) {
#ifdef __linux__
        alignas(struct inotify_event) char buffer[8192];
        bool changed = false;
        for (size_t attempts = 0; attempts < 32; ++attempts) {
            const ssize_t amount = read(fd_, buffer, sizeof(buffer));
            if (amount < 0 && errno == EINTR) continue;
            if (amount < 0 && errno == EAGAIN) {
                if (unavailable) {
                    close(fd_);
                    fd_ = -1;
                    directory_.clear();
                }
                return changed;
            }
            if (amount <= 0) {
                unavailable = true;
                close(fd_);
                fd_ = -1;
                directory_.clear();
                return true;
            }
            for (size_t offset = 0; offset < static_cast<size_t>(amount);) {
                if (static_cast<size_t>(amount) - offset < sizeof(struct inotify_event)) { unavailable = true; return true; }
                const struct inotify_event* event = reinterpret_cast<const struct inotify_event*>(buffer + offset);
                if (event->len > static_cast<size_t>(amount) - offset - sizeof(struct inotify_event)) { unavailable = true; return true; }
                const bool lost = event->mask & (IN_Q_OVERFLOW | IN_IGNORED | IN_UNMOUNT | IN_DELETE_SELF | IN_MOVE_SELF);
                if (lost) unavailable = true;
                if (!event->len || lost) changed = true;
                else {
                    size_t length = 0;
                    while (length < event->len && event->name[length]) ++length;
                    if (length == event->len) { unavailable = true; return true; }
                    const std::string name(event->name, length);
                    for (const char* credential : kCredentialFileNames) if (name == credential) changed = true;
                }
                offset += sizeof(struct inotify_event) + event->len;
            }
        }
        unavailable = true;
        close(fd_);
        fd_ = -1;
        directory_.clear();
        return true;
#else
        (void)unavailable;
        return false;
#endif
    }
private:
#ifdef __linux__
    int fd_ = -1;
    std::string directory_;
#endif
};

} // namespace detail

class Observer {
public:
    typedef std::function<bool(unsigned char*, size_t)> RandomSource;
    typedef std::function<std::string(const std::string&)> NormalizeStorefront;
    typedef std::function<bool(CachedCredentials&)> CredentialsSource;
    typedef std::function<UpstreamResponse(const std::string&, const std::string&)> Transport;
    explicit Observer(RandomSource random = os_random, NormalizeStorefront normalize = NormalizeStorefront()) : normalize_(normalize) {
        unsigned char bytes[16];
        if (!random(bytes, sizeof(bytes))) return;
        const char* hex = "0123456789abcdef";
        for (unsigned char byte : bytes) { nonce_ += hex[byte >> 4]; nonce_ += hex[byte & 15]; }
    }
    Observation observe(const std::string& directory, const CredentialsSource& cached_source, const Transport& transport) {
        std::unique_lock<std::mutex> lock(mutex_, std::try_to_lock);
        if (nonce_.empty()) return result(Error::ObserverUnavailable);
        if (!lock.owns_lock()) return result(Error::ObserverBusy);
        try {
            if (!events_.start(directory)) return changed(Error::ObserverUnavailable);
            bool unavailable = false;
            if (events_.changed(unavailable)) return changed(unavailable ? Error::ObserverUnavailable : Error::CredentialContextChanged);
            const detail::Files before = detail::read_files(directory);
            if (!before.valid) { previous_versions_.clear(); return changed(Error::CredentialsUnavailable); }
            if (!previous_versions_.empty() && previous_versions_ != before.versions) {
                previous_versions_ = before.versions;
                return changed(Error::CredentialContextChanged);
            }
            previous_versions_ = before.versions;
            CachedCredentials cached;
            if (!cached_source(cached)) return result(Error::ObserverBusy);
            const std::string region = normalize_ ? normalize_(before.storefront) : before.storefront;
            if (cached.generation == 0 || !header_valid(before.dev_token) || !header_valid(before.music_token) || !region_valid(region) ||
                before.dev_token != cached.dev_token || before.music_token != cached.music_token || region != cached.storefront) {
                return changed(Error::CredentialsUnavailable);
            }
            if (cached_generation_ != 0 && cached_generation_ != cached.generation) {
                cached_generation_ = cached.generation;
                return changed(Error::CredentialContextChanged);
            }
            cached_generation_ = cached.generation;
            if (events_.changed(unavailable)) return changed(unavailable ? Error::ObserverUnavailable : Error::CredentialContextChanged);
            if (counter_.load() >= kCounterLimit) return result(Error::ObserverUnavailable);
            const UpstreamResponse response = transport(cached.dev_token, cached.music_token);
            CachedCredentials after_cached;
            const detail::Files after = detail::read_files(directory);
            if (events_.changed(unavailable) || !after.valid || before.versions != after.versions ||
                before.dev_token != after.dev_token || before.music_token != after.music_token || before.storefront != after.storefront ||
                !cached_source(after_cached) || !(cached == after_cached)) {
                previous_versions_ = after.valid ? after.versions : "";
                return changed(unavailable ? Error::ObserverUnavailable : Error::CredentialContextChanged);
            }
            if (!response.transport_ok) return result(Error::UpstreamUnavailable);
            if (response.status != 200) return result(Error::UpstreamRejected);
            std::string storefront;
            if (!detail::storefront_response(response.body, storefront)) return result(Error::InvalidUpstreamResponse);
            if (storefront != region) return changed(Error::CredentialContextChanged);
            Observation observed = result(Error::None);
            observed.authenticated = true;
            observed.storefront = storefront;
            return observed;
        } catch (...) {
            return changed(Error::ObserverUnavailable);
        }
    }
private:
    Observation result(Error error) const {
        Observation observation;
        observation.error = error;
        if (!nonce_.empty()) observation.session_revision = nonce_ + ":" + std::to_string(counter_.load());
        return observation;
    }
    Observation changed(Error error) {
        if (counter_.load() < kCounterLimit) ++counter_;
        return result(error);
    }
    std::mutex mutex_;
    std::atomic<uint64_t> counter_{1};
    uint64_t cached_generation_ = 0;
    std::string nonce_, previous_versions_;
    NormalizeStorefront normalize_;
    detail::DirectoryEvents events_;
};

} // namespace waves_lite_session
