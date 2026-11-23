// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Waves contributors
#pragma once

#include "session_observer.h"
#include <chrono>
#include <poll.h>
#include <signal.h>
#include <sys/resource.h>
#include <sys/wait.h>

extern char** environ;

namespace waves_lite_session {

// The SDK's opaque request allocations have no checked release operation.
// Acquire in a fresh executable so process exit reclaims every SDK object.
class DeveloperChild {
public:
    DeveloperChild(pid_t process, int channel) : process_(process), channel_(channel) {}
    ~DeveloperChild() {
        close(channel_);
        if (!reaped_) {
            kill(process_, SIGKILL);
            while (waitpid(process_, &status_, 0) < 0 && errno == EINTR) {}
        }
    }
    std::string receive() {
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
        std::string token;
        bool eof = false;
        while (std::chrono::steady_clock::now() < deadline) {
            if (!reaped_) {
                const pid_t result = waitpid(process_, &status_, WNOHANG);
                if (result == process_) reaped_ = true;
                else if (result < 0 && errno != EINTR) {
                    if (errno == ECHILD) reaped_ = true;
                    return "";
                }
            }
            if (reaped_ && (!WIFEXITED(status_) || WEXITSTATUS(status_) != 0)) return "";
            if (eof && reaped_) return header_valid(token) ? token : "";
            if (eof) { poll(nullptr, 0, 20); continue; }
            struct pollfd descriptor = {channel_, POLLIN, 0};
            const int ready = poll(&descriptor, 1, 20);
            if (ready < 0) { if (errno == EINTR) continue; return ""; }
            if (descriptor.revents & (POLLERR | POLLNVAL)) return "";
            if (!(descriptor.revents & (POLLIN | POLLHUP))) continue;
            char buffer[1024];
            const ssize_t amount = read(channel_, buffer, sizeof(buffer));
            if (amount < 0) { if (errno == EINTR) continue; return ""; }
            if (!amount) { eof = true; continue; }
            if (static_cast<size_t>(amount) > kTokenLimit - token.size()) return "";
            token.append(buffer, static_cast<size_t>(amount));
        }
        return "";
    }
private:
    pid_t process_;
    int channel_, status_ = 0;
    bool reaped_ = false;
};

inline std::string read_developer_process(const std::string& directory, const char* executable) {
    int channel[2];
    if (pipe(channel) != 0) return "";
    // Keep all handoff descriptors above the fixed private output descriptor.
    for (int i = 0; i < 2; ++i) {
        const int owned = fcntl(channel[i], F_DUPFD_CLOEXEC, 4);
        close(channel[i]);
        channel[i] = owned;
        if (owned < 0) { close(channel[1 - i]); return ""; }
    }
    const int opened_sink = open("/dev/null", O_RDWR | O_CLOEXEC);
    const int sink = opened_sink < 0 ? -1 : fcntl(opened_sink, F_DUPFD_CLOEXEC, 4);
    if (opened_sink >= 0) close(opened_sink);
    struct rlimit files;
    if (sink < 0 || getrlimit(RLIMIT_NOFILE, &files) != 0 || files.rlim_cur > 1048576) {
        if (sink >= 0) close(sink);
        close(channel[0]); close(channel[1]);
        return "";
    }
    char* const arguments[] = {const_cast<char*>(executable), const_cast<char*>("--waves-session-developer"),
        const_cast<char*>("--base-dir"), const_cast<char*>(directory.c_str()), nullptr};
    const pid_t process = fork();
    if (process == 0) {
        // After a multithreaded fork, perform only async-signal-safe operations
        // until exec resets mutexes and all native SDK state.
        if (dup2(sink, 0) < 0 || dup2(sink, 1) < 0 || dup2(sink, 2) < 0 ||
            dup2(channel[1], 3) < 0) _exit(127);
        for (rlim_t fd = 4; fd < files.rlim_cur; ++fd) close(static_cast<int>(fd));
        execve(executable, arguments, ::environ);
        _exit(127);
    }
    close(sink); close(channel[1]);
    if (process < 0) { close(channel[0]); return ""; }
    DeveloperChild child(process, channel[0]);
    return child.receive();
}

inline bool developer_output_ready() {
    struct stat info;
    return fstat(3, &info) == 0 && S_ISFIFO(info.st_mode) && info.st_uid == getuid() &&
        fcntl(3, F_SETFD, FD_CLOEXEC) == 0;
}

inline bool write_developer_token(const std::string& token) {
    if (!header_valid(token)) return false;
    size_t offset = 0;
    while (offset < token.size()) {
        const ssize_t amount = write(3, token.data() + offset, token.size() - offset);
        if (amount < 0 && errno == EINTR) continue;
        if (amount <= 0) return false;
        offset += static_cast<size_t>(amount);
    }
    return true;
}

} // namespace waves_lite_session
