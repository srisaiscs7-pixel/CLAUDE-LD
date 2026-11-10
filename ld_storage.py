"""Where jobs and finished files are kept.

LocalStorage keeps everything in a folder next to the app. On Streamlit Community Cloud that folder is
wiped when the app restarts, so GitHubStorage can also copy every job into a private GitHub repository,
which makes your dissertations available from any device and safe across restarts.
"""
from __future__ import annotations

import base64
import json
import shutil
import threading
import time
from pathlib import Path

import requests


class LocalStorage:
    def __init__(self, root: str = "data/jobs"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _p(self, job_id, name):
        d = self.root / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    def write_json(self, job_id, name, obj, force=False):
        p = self._p(job_id, name)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with self._lock:
            tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(p)

    def read_json(self, job_id, name, default=None):
        p = self.root / job_id / name
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def write_bytes(self, job_id, name, data: bytes, force=True):
        self._p(job_id, name).write_bytes(data)

    def read_bytes(self, job_id, name):
        p = self.root / job_id / name
        return p.read_bytes() if p.exists() else None

    def list_jobs(self):
        return sorted([d.name for d in self.root.iterdir() if d.is_dir()], reverse=True)

    def delete_job(self, job_id):
        shutil.rmtree(self.root / job_id, ignore_errors=True)

    def flush(self, job_id):
        pass

    label = "this app's own disk (cleared if the app restarts)"


class GitHubStorage(LocalStorage):
    """Local cache plus a copy in a private GitHub repo (jobs/<job_id>/<file>)."""

    def __init__(self, token: str, repo: str, branch: str = "main", root: str = "data/jobs"):
        super().__init__(root)
        self.repo = repo
        self.branch = branch
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28"}
        self._sha = {}
        self._last_push = {}
        self._dirty = set()
        self.label = f"your private GitHub repository {repo}"

    def _url(self, path):
        return f"https://api.github.com/repos/{self.repo}/contents/{path}"

    def _push(self, job_id, name, data: bytes):
        path = f"jobs/{job_id}/{name}"
        sha = self._sha.get(path)
        if sha is None:
            r = requests.get(self._url(path), headers=self.h, params={"ref": self.branch}, timeout=30)
            if r.status_code == 200:
                sha = r.json().get("sha")
        body = {"message": f"{job_id}: {name}", "content": base64.b64encode(data).decode(), "branch": self.branch}
        if sha:
            body["sha"] = sha
        for attempt in range(3):
            r = requests.put(self._url(path), headers=self.h, json=body, timeout=60)
            if r.status_code in (200, 201):
                self._sha[path] = r.json()["content"]["sha"]
                self._last_push[path] = time.time()
                self._dirty.discard((job_id, name))
                return
            if r.status_code == 409 or r.status_code == 422:  # stale sha: refetch and retry
                g = requests.get(self._url(path), headers=self.h, params={"ref": self.branch}, timeout=30)
                if g.status_code == 200:
                    body["sha"] = g.json().get("sha")
                continue
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"GitHub save failed ({r.status_code}): {r.text[:200]}")

    def write_json(self, job_id, name, obj, force=False):
        super().write_json(job_id, name, obj)
        path = f"jobs/{job_id}/{name}"
        if force or time.time() - self._last_push.get(path, 0) > 45:
            try:
                self._push(job_id, name, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
            except Exception:
                self._dirty.add((job_id, name))
        else:
            self._dirty.add((job_id, name))

    def write_bytes(self, job_id, name, data: bytes, force=True):
        super().write_bytes(job_id, name, data)
        self._push(job_id, name, data)

    def flush(self, job_id):
        for jid, name in list(self._dirty):
            if jid == job_id:
                p = self.root / jid / name
                if p.exists():
                    try:
                        self._push(jid, name, p.read_bytes())
                    except Exception:
                        pass

    def _fetch(self, job_id, name):
        path = f"jobs/{job_id}/{name}"
        h = dict(self.h, Accept="application/vnd.github.raw+json")
        r = requests.get(self._url(path), headers=h, params={"ref": self.branch}, timeout=60)
        if r.status_code == 200:
            p = self._p(job_id, name)
            p.write_bytes(r.content)
            return r.content
        return None

    def read_json(self, job_id, name, default=None):
        p = self.root / job_id / name
        if not p.exists():
            self._fetch(job_id, name)
        return super().read_json(job_id, name, default)

    def read_bytes(self, job_id, name):
        data = super().read_bytes(job_id, name)
        return data if data is not None else self._fetch(job_id, name)

    def list_jobs(self):
        local = set(super().list_jobs())
        try:
            r = requests.get(self._url("jobs"), headers=self.h, params={"ref": self.branch}, timeout=30)
            if r.status_code == 200:
                local |= {x["name"] for x in r.json() if x.get("type") == "dir"}
        except requests.RequestException:
            pass
        return sorted(local, reverse=True)

    def delete_job(self, job_id):
        super().delete_job(job_id)
        r = requests.get(self._url(f"jobs/{job_id}"), headers=self.h, params={"ref": self.branch}, timeout=30)
        if r.status_code == 200:
            for f in r.json():
                requests.delete(self._url(f["path"]), headers=self.h, timeout=30,
                                json={"message": f"delete {f['path']}", "sha": f["sha"], "branch": self.branch})

    def check(self) -> str:
        r = requests.get(f"https://api.github.com/repos/{self.repo}", headers=self.h, timeout=20)
        if r.status_code != 200:
            return f"Failed: HTTP {r.status_code} {r.text[:120]}"
        perms = r.json().get("permissions", {})
        return "OK" if perms.get("push") or perms.get("admin") or perms == {} else "Read-only token"
