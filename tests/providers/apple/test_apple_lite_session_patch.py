"""The source extension observes a fresh session without exposing credentials."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
SOURCE = Path(__file__).resolve().parents[3] / "tools" / "apple_lite_session"


@pytest.fixture(scope="module")
def observer_program(tmp_path_factory):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("a C++11 host compiler is required for the source extension contract")
    folder = tmp_path_factory.mktemp("lite-session-observer")
    source = folder / "observe.cpp"
    source.write_text(
        r"""
#include "session_observer.h"
#include <fstream>
#include <iostream>
using namespace waves_lite_session;
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    const std::string mode = argv[2], directory = argv[1];
    std::string body((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
    Observer observer([&mode](unsigned char* out, size_t n) {
        if (mode == "seed_failed") return false;
        for (size_t i = 0; i < n; ++i) out[i] = 0x42;
        return true;
    });
    CachedCredentials cached;
    cached.dev_token = "synthetic-developer";
    cached.music_token = "synthetic-user";
    cached.storefront = "ro";
    cached.generation = 1;
    if (mode == "cache_mismatch") cached.music_token = "different-synthetic-user";
    size_t calls = 0;
    std::string busy;
    const Observer::CredentialsSource source = [&cached](CachedCredentials& out) {
        out = cached;
        return true;
    };
    const Observer::Transport transport = [&](const std::string& dev, const std::string& music) {
        ++calls;
        if (dev != "synthetic-developer" || music != "synthetic-user") throw std::runtime_error("private error");
        if (mode == "transport_exception") throw std::runtime_error("private-upstream-secret");
        if (mode == "cached_aba") cached.generation += 2;
        if (calls == 1 && (mode == "replace" || mode == "file_aba")) {
            const std::string file = directory + "/MUSIC_TOKEN";
            const std::string replacement = directory + "/swap";
            if (mode == "file_aba" && rename(file.c_str(), (directory + "/retained").c_str()) != 0) return UpstreamResponse();
            std::ofstream stream(replacement);
            stream << "synthetic-user";
            stream.close();
            chmod(replacement.c_str(), 0600);
            if (rename(replacement.c_str(), file.c_str()) != 0) return UpstreamResponse();
            if (mode == "file_aba" && rename((directory + "/retained").c_str(), file.c_str()) != 0) return UpstreamResponse();
        }
        if (mode == "remove") unlink((directory + "/MUSIC_TOKEN").c_str());
        if (mode == "busy") busy = observer.observe(directory, source, [](const std::string&, const std::string&) { return UpstreamResponse(); }).json();
        UpstreamResponse response;
        response.status = mode == "unauthorized" ? 401 : mode == "forbidden" ? 403 : mode == "redirect" ? 302 : 200;
        response.transport_ok = mode != "transport_failed";
        response.body = body;
        return response;
    };
    std::cout << observer.observe(directory, source, transport).json() << std::endl;
    if (mode == "replace") std::cout << observer.observe(directory, source, transport).json() << std::endl;
    std::cout << "{\"calls\":" << calls << ",\"busy\":" << (busy.empty() ? "null" : busy) << "}" << std::endl;
}
"""
    )
    binary = folder / "observe"
    result = subprocess.run(  # noqa: S603 (fixed compiler argv and owned synthetic source)
        [
            compiler,
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            "-I",
            str(SOURCE),
            str(source),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary


def credentials(tmp_path):
    directory = tmp_path / "synthetic-session"
    directory.mkdir(mode=0o700)
    for name, value in {
        "DEV_TOKEN": "synthetic-developer",
        "MUSIC_TOKEN": "synthetic-user",
        "STOREFRONT_ID": "ro",
    }.items():
        file = directory / name
        file.write_text(value)
        file.chmod(0o600)
    return directory


def test_fresh_authenticated_storefront_is_reported_without_credentials(observer_program, tmp_path):
    packets, result = observe(observer_program, credentials(tmp_path))
    packet = packets[0]
    assert packet == {
        "protocol": "waves-lite-session-v1",
        "authenticated": True,
        "storefront": "ro",
        "account_id": "",
        "session_revision": "42" * 16 + ":1",
        "error": "",
    }
    assert "synthetic-user" not in result.stdout
    assert "synthetic-developer" not in result.stdout


VALID_BODY = '{"data":[{"id":"ro","type":"storefronts"}]}'


def observe(program, directory, mode="success", body=VALID_BODY):
    result = subprocess.run(  # noqa: S603 (owned observer and synthetic credential directory)
        [str(program), str(directory), mode], input=body, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines()], result


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("unauthorized", "upstream_rejected"),
        ("forbidden", "upstream_rejected"),
        ("redirect", "upstream_rejected"),
        ("transport_failed", "upstream_unavailable"),
        ("transport_exception", "observer_unavailable"),
        ("cache_mismatch", "credentials_unavailable"),
        ("cached_aba", "credential_context_changed"),
        ("file_aba", "credential_context_changed"),
        ("remove", "credential_context_changed"),
        ("seed_failed", "observer_unavailable"),
    ],
)
def test_failed_or_changed_context_never_advertises_authentication(observer_program, tmp_path, mode, error):
    packets, result = observe(observer_program, credentials(tmp_path), mode)
    packet = packets[0]
    assert packet["authenticated"] is None
    assert packet["storefront"] == ""
    assert packet["account_id"] == ""
    assert packet["error"] == error
    assert "private" not in result.stdout
    assert "synthetic" not in result.stdout
    if mode == "seed_failed":
        assert packet["session_revision"] == ""
        assert packets[-1]["calls"] == 0
    else:
        assert packet["session_revision"].startswith("42" * 16 + ":")


@pytest.mark.parametrize(
    "body",
    [
        '{"data":[],"secret":"upstream-secret"}',
        '{"data":[{"id":"ro","type":"songs"}]}',
        '{"data":[{"id":"RO","type":"storefronts"}]}',
        '{"data":[{"id":true,"type":"storefronts"}]}',
        '{"data":[{"id":"ro","id":"ro","type":"storefronts"}]}',
        VALID_BODY[:-1] + ',"data":[]}',
        VALID_BODY + "trailing",
        VALID_BODY[:-1] + ',"errors":[]}',
        '{"data":[{"id":"ro","type":"storefronts","attributes":{"x":"\\ud800"}}]}',
        '{"data":[{"id":"ro","type":"storefronts","attributes":{"x":' + "[" * 17 + "0" + "]" * 17 + "}}]}",
        " " * 65537,
    ],
)
def test_malformed_or_unbounded_reply_remains_unknown(observer_program, tmp_path, body):
    packets, result = observe(observer_program, credentials(tmp_path), body=body)
    assert packets[0]["authenticated"] is None
    assert packets[0]["error"] == "invalid_upstream_response"
    assert "upstream-secret" not in result.stdout


def test_same_bytes_replacement_revokes_confirmation_continuity_then_can_be_freshly_observed(
    observer_program, tmp_path
):
    packets, _ = observe(observer_program, credentials(tmp_path), "replace")
    assert packets[0]["authenticated"] is None
    assert packets[0]["error"] == "credential_context_changed"
    assert packets[0]["session_revision"] == "42" * 16 + ":2"
    assert packets[1]["authenticated"] is True
    assert packets[1]["session_revision"] == packets[0]["session_revision"]


def test_a_concurrent_observer_does_not_start_another_request(observer_program, tmp_path):
    packets, _ = observe(observer_program, credentials(tmp_path), "busy")
    assert packets[0]["authenticated"] is True
    assert packets[-1]["calls"] == 1
    assert packets[-1]["busy"]["authenticated"] is None
    assert packets[-1]["busy"]["error"] == "observer_busy"


@pytest.mark.parametrize("change", ["missing", "symlink", "public", "header_injection", "oversized"])
def test_unsafe_owned_credential_file_prevents_contact(observer_program, tmp_path, change):
    directory = credentials(tmp_path)
    token = directory / "MUSIC_TOKEN"
    if change == "missing":
        token.unlink()
    elif change == "symlink":
        target = directory / "synthetic-target"
        token.rename(target)
        token.symlink_to(target)
    elif change == "public":
        token.chmod(0o644)
    elif change == "header_injection":
        token.write_text("synthetic-user\r\nInjected: secret")
    else:
        token.write_text("x" * 8193)
    packets, _ = observe(observer_program, directory)
    assert packets[0]["authenticated"] is None
    assert packets[0]["error"] == "credentials_unavailable"
    assert packets[-1]["calls"] == 0


def test_wiring_patch_contains_the_tested_observer_and_exact_source_outputs():
    # The compiled observation tests above prove the behavior. This pin keeps
    # the separately applied source patch from drifting from those headers.
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    assert hashlib.sha256((SOURCE / "session-observer.patch").read_bytes()).hexdigest() == manifest["patch_sha256"]
    for name in ("session_observer.h", "session_transport.h"):
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == manifest["outputs"]["lite/" + name]
        section = (SOURCE / "session-observer.patch").read_text().split("+++ b/lite/" + name + "\n", 1)[1]
        added = []
        for line in section.splitlines(keepends=True):
            if line.startswith("--- "):
                break
            if line.startswith("+"):
                added.append(line[1:])
        assert "".join(added) == (SOURCE / name).read_text()


def test_source_extension_refuses_unchecked_source_without_changing_it(tmp_path):
    marker = tmp_path / "unrelated-source.txt"
    marker.write_text("preserve this source")
    result = subprocess.run(  # noqa: S603 (the public source command and an owned fixture directory)
        [sys.executable, str(SOURCE / "apply.py"), "--source", str(tmp_path), "--apply"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "prerequisites do not match" in result.stdout
    assert marker.read_text() == "preserve this source"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["unrelated-source.txt"]


@pytest.fixture(scope="module")
def native_transport_program(tmp_path_factory):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("a C++11 host compiler is required for the source extension contract")
    folder = tmp_path_factory.mktemp("lite-native-transport")
    (folder / "lite.h").write_text(r"""
#pragma once
#include <map>
#include <string>
#include <vector>
enum {
CURLOPT_URL, CURLOPT_WRITEFUNCTION, CURLOPT_WRITEDATA, CURLOPT_HTTPHEADER,
CURLOPT_SSL_VERIFYPEER, CURLOPT_SSL_VERIFYHOST, CURLOPT_FOLLOWLOCATION, CURLOPT_MAXREDIRS,
CURLOPT_PROTOCOLS, CURLOPT_REDIR_PROTOCOLS, CURLOPT_TIMEOUT_MS, CURLOPT_CONNECTTIMEOUT_MS,
CURLOPT_ACCEPT_ENCODING
};
const long CURLPROTO_HTTPS = 2;
extern std::string mode;
extern size_t calls;
struct CurlSlist {
    void* list = this;
    bool ok = true;
    std::vector<std::string> entries;
    bool append(const char* value) { entries.push_back(value); return mode != "headers_failed"; }
};
struct CurlEasy {
    bool ok;
    std::map<int, long> numbers;
    std::map<int, std::string> strings;
    std::map<int, void*> pointers;
    explicit CurlEasy(const char* = nullptr) : ok(mode != "create_failed") {}
    bool setOptInt(int option, long value) { numbers[option] = value; return mode != "option_failed"; }
    bool setOptStr(int option, const char* value) { strings[option] = value; return mode != "option_failed"; }
    bool setOptPtr(int option, void* value) { pointers[option] = value; return mode != "option_failed"; }
    bool perform();
    long getResponseCode() { return mode == "invalid_status" ? -1 : mode == "rejected" ? 403 : 200; }
};
""")
    source = folder / "transport.cpp"
    source.write_text(r"""
#include "session_transport.h"
#include <iostream>
std::string mode;
size_t calls = 0;
bool CurlEasy::perform() {
    ++calls;
    const CurlSlist* headers = static_cast<CurlSlist*>(pointers[CURLOPT_HTTPHEADER]);
    if (mode == "perform_failed" || !headers ||
        headers->entries != std::vector<std::string>{"Authorization: Bearer synthetic-developer", "Music-User-Token: synthetic-user", "Accept: application/json"} ||
        strings[CURLOPT_URL] != "https://api.music.apple.com/v1/me/storefront" ||
        strings[10004] != "" || strings[10177] != "*" || strings[CURLOPT_ACCEPT_ENCODING] != "identity" ||
        numbers[CURLOPT_SSL_VERIFYPEER] != 1 || numbers[CURLOPT_SSL_VERIFYHOST] != 2 ||
        numbers[CURLOPT_FOLLOWLOCATION] != 0 || numbers[CURLOPT_MAXREDIRS] != 0 ||
        numbers[CURLOPT_PROTOCOLS] != CURLPROTO_HTTPS || numbers[CURLOPT_REDIR_PROTOCOLS] != CURLPROTO_HTTPS ||
        numbers[CURLOPT_TIMEOUT_MS] != 5000 || numbers[CURLOPT_CONNECTTIMEOUT_MS] != 2000) return false;
    std::string body = mode == "overflow" ? std::string(65537, 'x') : "{\"data\":[{\"id\":\"ro\",\"type\":\"storefronts\"}]}";
    typedef size_t (*Writer)(char*, size_t, size_t, void*);
    const Writer writer = reinterpret_cast<Writer>(pointers[CURLOPT_WRITEFUNCTION]);
    return writer && writer(&body[0], 1, body.size(), pointers[CURLOPT_WRITEDATA]) == body.size();
}
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    mode = argv[2];
    waves_lite_session::Observer observer;
    const waves_lite_session::Observation observation = observer.observe(argv[1], [](waves_lite_session::CachedCredentials& out) {
        out.dev_token = "synthetic-developer";
        out.music_token = "synthetic-user";
        out.storefront = "ro";
        out.generation = 1;
        return true;
    }, waves_lite_session::request_storefront);
    std::cout << observation.json() << std::endl << "{\"calls\":" << calls << "}" << std::endl;
}
""")
    binary = folder / "transport"
    result = subprocess.run(  # noqa: S603 (fixed compiler argv and owned synthetic native API adapter)
        [
            compiler,
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            "-I",
            str(folder),
            "-I",
            str(SOURCE),
            str(source),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize(
    ("mode", "authenticated", "calls"),
    [
        ("success", True, 1),
        ("create_failed", None, 0),
        ("headers_failed", None, 0),
        ("option_failed", None, 0),
        ("perform_failed", None, 1),
        ("overflow", None, 1),
        ("invalid_status", None, 1),
        ("rejected", None, 1),
    ],
)
def test_native_transport_requires_verified_fixed_request_and_truthful_failures(
    native_transport_program, tmp_path, mode, authenticated, calls
):
    packets, result = observe(native_transport_program, credentials(tmp_path), mode)
    assert packets[0]["authenticated"] is authenticated
    assert packets[-1]["calls"] == calls
    assert packets[0]["storefront"] == ("ro" if authenticated else "")
    assert "synthetic" not in result.stdout
