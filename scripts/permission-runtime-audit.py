"""Exercise role assignments against a disposable API on port 8010."""

import json
import os
import secrets
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010/api/v1"


def call(path, method="GET", body=None, token=""):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, json.loads(payload) if payload else {}


def require(path, status, token, method="GET", body=None):
    actual, payload = call(path, method, body, token)
    assert actual == status, (path, actual, payload)
    return payload


def main():
    admin_password = os.environ["CV_ARCHIVE_AUDIT_ADMIN_PASSWORD"]
    role_password = secrets.token_urlsafe(18)
    admin = require("/auth/login", 200, "", "POST", {"username": "admin", "password": admin_password})["access_token"]
    cases = [
        ("library", ["library"], [], [("/assets", 200), ("/datasets", 403), ("/system/overview", 403), ("/jobs", 403)]),
        ("overview", ["overview"], [], [("/system/overview", 200), ("/assets", 403), ("/datasets", 403)]),
        ("datasets", ["datasets", "downloads"], ["export_create"], [("/datasets", 200), ("/jobs", 200), ("/assets", 403), ("/system/overview", 403)]),
    ]
    for key, menus, actions, routes in cases:
        role = require("/role-templates", 201, admin, "POST", {
            "name": f"权限实测{key}", "menu_permissions": menus, "action_permissions": actions,
        })
        username = f"role_audit_{key}"
        require("/users", 201, admin, "POST", {
            "username": username, "password": role_password, "roles": ["custom"],
            "role_template_id": role["id"], "menu_permissions": menus, "action_permissions": actions,
        })
        token = require("/auth/login", 200, "", "POST", {"username": username, "password": role_password})["access_token"]
        permissions = require("/permissions/me", 200, token)
        assert {item["key"] for item in permissions["menus"]} == set(menus), permissions
        assert {item["key"] for item in permissions["actions"]} == set(actions), permissions
        for path, status in routes:
            require(path, status, token)
        require("/tag-definitions", 403 if key == "overview" else 200, token)
        require("/tag-definitions", 403, token, "POST", {"key": "audit_tag", "name": "测试标签"})
        print(f"{key}: menu={len(menus)} action={len(actions)} route_checks={len(routes)+2} passed")


if __name__ == "__main__":
    main()
