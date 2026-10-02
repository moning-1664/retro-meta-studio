"""Scraper bridge endpoints. Api supplies workspace, registry and job state."""
from __future__ import annotations
import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
try:
    import requests
except ImportError:
    requests = None
from adapters import get_adapter
from app.model.plan import Plan, RESOLVE_OVERWRITE
from app.plan import builder
from app.plan.applier import apply_plan
from app.plan.validator import validate
from app.archive import service as archive_service
from app.scrape.providers import ScreenScraperClient, ScreenScraperConfig
from app.scrape.providers.screenscraper import SYSTEM_IDS, _system_id
from app.scrape import secrets as scrape_secrets
from bridge.responses import ok, err, guarded
log = logging.getLogger("bridge.api")


class ScraperBridge:
    def _screen_scraper_client(self):
        public = (self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("scraper") or {}
        protected = self.registry.get_setting(self.SCRAPER_SECRET_KEY, {}) or {}
        return ScreenScraperClient(ScreenScraperConfig(
            dev_id=scrape_secrets.load(protected.get("devId") or ""),
            dev_password=scrape_secrets.load(protected.get("devPassword") or ""),
            soft_name=str(public.get("softName") or "RetroMetaStudio"),
            user_id=str(public.get("userId") or ""),
            user_password=scrape_secrets.load(protected.get("userPassword") or ""),
            # 작은 ROM과 단일 파일 ZIP은 해시를 우선한다. 대용량 파일과
            # 다중 파일 ZIP은 provider에서 전체 읽기를 피한다.
            use_hashes=bool(public.get("useHashes", True)),
            media_types=tuple(public["mediaTypes"]) if "mediaTypes" in public else None,
        ))

    @guarded
    def scraper_settings(self):
        public = dict((self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {}).get("scraper") or {})
        protected = self.registry.get_setting(self.SCRAPER_SECRET_KEY, {}) or {}
        public.update({"devIdSet": bool(protected.get("devId")),
                       "devPasswordSet": bool(protected.get("devPassword")),
                       "userPasswordSet": bool(protected.get("userPassword"))})
        return ok(public)

    @guarded
    def scraper_systems(self):
        return ok([{"name": name, "id": system_id}
                   for name, system_id in sorted(SYSTEM_IDS.items())
                   if name != "vita" and (system_id != 75 or name == "arcade")])

    @guarded
    def save_scraper_settings(self, patch):
        if not isinstance(patch, dict):
            return err("스크래퍼 설정 형식이 올바르지 않습니다.")
        settings = dict(self.registry.get_setting(self.APP_SETTINGS_KEY, {}) or {})
        public = dict(settings.get("scraper") or {})
        for key in ("enabled", "softName", "userId", "useHashes", "mediaTypes"):
            if key in patch:
                public[key] = patch[key]
        settings["scraper"] = public
        self.registry.set_setting(self.APP_SETTINGS_KEY, settings)
        protected = dict(self.registry.get_setting(self.SCRAPER_SECRET_KEY, {}) or {})
        for key in ("devId", "devPassword", "userPassword"):
            if key in patch and patch[key] is not None:
                value = str(patch[key])
                if value:
                    protected[key] = scrape_secrets.store(f"scraper/{key}", value)
                else:
                    scrape_secrets.delete(protected.get(key) or "")
                    protected.pop(key, None)
        self.registry.set_setting(self.SCRAPER_SECRET_KEY, protected)
        return self.scraper_settings()

    @guarded
    def start_scraper_account_status(self):
        job_id = self.jobs.run(lambda cb: self._scraper_account_job(cb), mutates_state=False)
        return ok({"jobId": job_id})

    @guarded
    def dat_sources(self):
        return ok(self.dat_catalog.sources())

    @guarded
    def start_dat_import(self, file_path, system):
        if not file_path or not Path(file_path).is_file():
            return err("DAT XML 파일을 선택하세요.")
        if not str(system or "").strip():
            return err("DAT에 대응할 System을 선택하세요.")
        job_id = self.jobs.run(
            lambda cb: self.dat_catalog.import_xml(file_path, system, cb),
            mutates_state=True)
        return ok({"jobId": job_id})

    def _scraper_account_job(self, progress):
        progress(0, 1, "ScreenScraper 계정 확인")
        status = self._screen_scraper_client().account_status()
        progress(1, 1, "연결됨")
        return status

    @guarded
    def create_scrape_session(self, target, collection_id=None, item_ids=None):
        target = str(target or "collection")
        ids = [str(value) for value in (item_ids or [])]
        if not ids:
            return err("스크랩할 게임을 선택하세요.")
        items = []
        if target == "archive":
            for identity_id in ids:
                detail = archive_service.detail(self.archive, identity_id)
                if detail is None:
                    continue
                path = next((source.get("abs_path") for source in detail.get("romSources") or []
                             if source.get("abs_path") and Path(source["abs_path"]).is_file()), None)
                items.append(self.scrape.item(
                    identity_id, detail["system"], detail["filename"], detail.get("fields"),
                    path=path, size=detail.get("size")))
        else:
            collection = self.registry.get_collection(collection_id)
            if collection is None:
                return err("Collection을 찾을 수 없습니다.")
            cache = self.workspace.open(collection_id)
            adapter = get_adapter(collection.frontend)
            for uid in ids:
                row = cache.get_row(int(uid))
                if row is None:
                    continue
                layout = adapter.layout(collection, row["system"])
                path = str(Path(layout.rom_dir) / row["filename"]) if layout.rom_dir else None
                items.append(self.scrape.item(uid, row["system"], row["filename"], row["fields"],
                                              path=path, size=row["size"]))
        if not items:
            return err("스크랩할 항목을 찾을 수 없습니다.")
        for item in items:
            match = self.registry.scrape_confirmed_match(
                target, collection_id, item["system"], item["filename"], item.get("size"))
            if match and match["provider"] == "screenscraper":
                item["confirmedGameId"] = match["remote_game_id"]
        session = self.scrape.sessions.create(target, collection_id, items)
        return ok({"id": session["id"], "target": target, "collectionId": collection_id,
                   "items": items, "quota": None})

    @guarded
    def scrape_session(self, session_id):
        return ok(self.scrape.sessions.get(session_id))

    @guarded
    def clear_scrape_confirmed_match(self, session_id, item_id):
        session = self.scrape.sessions.get(str(session_id))
        item = next((row for row in session["items"] if row["id"] == str(item_id)), None)
        if item is None:
            return err("스크랩할 항목을 찾을 수 없습니다.")
        self.registry.delete_scrape_confirmed_match(
            session["target"], session.get("collectionId"), item["system"],
            item["filename"], item.get("size"))
        system_id = _system_id(item.get("systemHint") or item["system"])
        if system_id:
            self.registry.delete_scrape_query_alias(
                "screenscraper", system_id, item.get("requestedQuery") or item["originalQuery"])
        item.pop("confirmedGameId", None)
        item.pop("aliasGameId", None)
        return ok({"cleared": True})

    @guarded
    def start_scrape_item(self, session_id, item_id, query=None, system_hint=None,
                          force_search=False):
        # Search is network and hash I/O. Keep it outside the UI thread; it does
        # not mutate Collection/Archive state until apply_scrape_session().
        session = self.scrape.sessions.get(str(session_id))
        item = next((row for row in session["items"] if row["id"] == str(item_id)), None)
        if item is None:
            return err("스크랩할 항목을 찾을 수 없습니다.")
        selected_system = item["system"] if system_hint is None else str(system_hint)
        system_id = _system_id(selected_system)
        item["aliasGameId"] = (self.registry.scrape_query_alias(
            "screenscraper", system_id, str(query or item["query"]).strip())
            if system_id else None)
        item["systemHint"] = selected_system
        job_id = self.jobs.run(
            lambda cb: self.scrape.search_item(str(session_id), str(item_id), query,
                                                system_hint, progress=cb,
                                                force_search=bool(force_search)),
            mutates_state=False)
        return ok({"jobId": job_id})

    @guarded
    def select_scrape_candidate(self, session_id, item_id, candidate_id, fields=None, media=None):
        selected = self.scrape.select(str(session_id), str(item_id), str(candidate_id),
                                      fields if fields is not None else None,
                                      media if media is not None else None)
        log.info("Scraper candidate selected item=%s candidate=%s fields=%d mediaIndexes=%s",
                 item_id, candidate_id, len(selected["selectedFields"]), selected["selectedMedia"])
        return ok(selected)

    @guarded
    def skip_scrape_item(self, session_id, item_id):
        return ok(self.scrape.skip(str(session_id), str(item_id)))

    @guarded
    def cancel_scrape_session(self, session_id):
        return ok(self.scrape.sessions.close(str(session_id)))

    @guarded
    def start_apply_scrape_session(self, session_id):
        with self._scrape_apply_lock:
            current = self._scrape_apply_jobs.get(str(session_id))
            job = self.jobs.get(current) if current else None
            if job and not job.get("done"):
                return ok({"jobId": current})
            result = self._start_apply_scrape_session(session_id)
            if result.get("ok"):
                self._scrape_apply_jobs[str(session_id)] = result["data"]["jobId"]
            return result

    def _start_apply_scrape_session(self, session_id):
        session = self.scrape.sessions.get(str(session_id))
        log.info("Scraper apply requested session=%s target=%s selected=%d total=%d",
                 session_id, session["target"],
                 sum(bool(self.scrape.proposal(item)) for item in session["items"]),
                 len(session["items"]))
        # The existing save_fields/media_paste APIs perform their own target
        # checks. A regular mutating job gives the operation the global write
        # lock without marking its own target busy and blocking those APIs.
        job_id = self.jobs.run(
            lambda cb: self._apply_scrape_session(str(session_id), cb), mutates_state=True)
        return ok({"jobId": job_id})

    def _download_scrape_media(self, url, session_id, item_id, media_type, media_format=""):
        parsed = urlparse(str(url or ""))
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (hostname == "screenscraper.fr" or hostname.endswith(".screenscraper.fr")):
            raise ValueError("허용되지 않은 미디어 주소입니다.")
        if requests is None:
            raise RuntimeError("미디어 다운로드 모듈(requests)이 설치되지 않았습니다.")
        allowed_suffixes = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".avi", ".pdf")
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in allowed_suffixes:
            suffix = "." + str(media_format or "").lower().lstrip(".")
        if suffix not in allowed_suffixes:
            suffix = ""
        name = hashlib.sha256(str(url).encode("utf-8")).hexdigest()
        folder = self._scrape_cache_dir / str(session_id) / str(item_id) / str(media_type)
        folder.mkdir(parents=True, exist_ok=True)
        for existing_suffix in allowed_suffixes:
            destination = folder / (name + existing_suffix)
            if destination.is_file():
                log.info("Scraper media cache hit item=%s type=%s bytes=%d format=%s",
                         item_id, media_type, destination.stat().st_size, existing_suffix)
                return str(destination)
        temporary = folder / (name + ".part")
        total = 0
        started = time.monotonic()
        try:
            with requests.get(url, timeout=30, stream=True) as response:
                response.raise_for_status()
                if not suffix:
                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    suffix = {"image/png": ".png", "image/jpeg": ".jpg",
                              "image/webp": ".webp", "image/gif": ".gif",
                              "video/mp4": ".mp4", "video/x-msvideo": ".avi",
                              "application/pdf": ".pdf"}.get(content_type, "")
                if not suffix:
                    raise ValueError("스크랩 미디어 파일 형식을 확인할 수 없습니다.")
                with temporary.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 256):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > 256 * 1024 * 1024:
                            raise ValueError("미디어 파일이 허용 크기를 넘었습니다.")
                        stream.write(chunk)
            destination = folder / (name + suffix)
            temporary.replace(destination)
            log.info("Scraper media download item=%s type=%s bytes=%d format=%s seconds=%.3f",
                     item_id, media_type, total, suffix, time.monotonic() - started)
            return str(destination)
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise RuntimeError(f"미디어 다운로드 실패 ({type(exc).__name__}, HTTP {status or '응답 없음'})") from None
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def _apply_scraped_collection_media(self, collection_id, rom_uid, downloaded):
        """Apply only this scraper's media, leaving the user's existing Plan alone."""
        collection, cache, provider = self._plan_context(collection_id)
        row = cache.get_row(int(rom_uid))
        if row is None:
            raise ValueError("스크랩 대상 게임을 찾을 수 없습니다.")
        blocked = self._ensure_file_ops(collection) or self._ensure_writable(collection, [row["system"]])
        if blocked:
            raise ValueError(blocked.get("error") or "미디어를 쓸 수 없습니다.")
        item = {"system": row["system"], "filename": row["filename"], "rom": None,
                "media": [{"type": media_type, "path": path, "size": Path(path).stat().st_size}
                          for media_type, path in downloaded],
                "fields": row["fields"], "frontend_raw": row["frontend_raw"]}
        stage_started = time.monotonic()
        plan = Plan(collection_id)
        result = builder.plan_add(plan, collection, provider, [item])
        log.info("Scraper media plan collection=%s romUid=%s added=%s skipped=%d conflicts=%s",
                 collection_id, rom_uid, result.get("added"), len(result.get("skipped") or []),
                 result.get("conflicts"))
        if result.get("added") != 1:
            raise ValueError("스크랩 미디어를 Plan에 올리지 못했습니다.")
        for key in result.pop("conflictKeys", []):
            builder.resolve_conflict(plan, collection, provider, key, RESOLVE_OVERWRITE)
        validation = validate(plan, collection, cache, provider)
        if not validation["ok"] and not validation["blocked"]:
            log.warning("Scraper media plan invalid collection=%s romUid=%s reasons=%s",
                        collection_id, rom_uid, validation.get("entries"))
            reason = next((problem.get("error") for problem in validation.get("entries") or []
                           if problem.get("error")), "미디어 Plan 검증에 실패했습니다.")
            raise ValueError(f"스크랩 미디어를 적용하지 못했습니다: {reason}")
        if validation["blocked"]:
            log.warning("Scraper media plan blocked collection=%s romUid=%s reasons=%s",
                        collection_id, rom_uid, validation)
            raise ValueError("스크랩 미디어를 저장할 공간이 부족합니다.")
        lock_name = f"apply:{collection_id}"
        if not self.registry.acquire_lock(lock_name, kind="apply"):
            raise ValueError("다른 창에서 같은 Collection을 적용하는 중입니다.")
        try:
            outcome = apply_plan(plan, collection, cache, self.registry, provider,
                                 disc_titles=self._disc_title_option())
            log.info("Scraper collection media apply collection=%s romUid=%s types=%s outcome=%s",
                     collection_id, rom_uid, [kind for kind, _ in downloaded], outcome)
        finally:
            self.registry.release_lock(lock_name)
        if (outcome.get("applied") != 1 or outcome.get("failed")
                or outcome.get("partial") or outcome.get("skipped")):
            raise ValueError("스크랩 미디어 적용이 완료되지 않았습니다. 로그를 확인하세요.")
        log.info("Scraper collection media pipeline collection=%s romUid=%s seconds=%.3f",
                 collection_id, rom_uid, time.monotonic() - stage_started)
        return outcome.get("systems") or []

    def _rebind_plan_rows(self, collection_id, systems):
        """A rescan assigns new cache IDs; keep pending Plan entries on their game."""
        plan = self._plans.get(collection_id)
        if not plan or not len(plan):
            return
        cache = self.workspace.open(collection_id)
        rows = {(row["system"], row["filename"]): row["rom_uid"]
                for row in cache.query_rows(systems=list(systems))}
        for entry in plan.entries:
            if entry.rom_uid is not None and entry.system in systems:
                entry.rom_uid = rows.get((entry.system, entry.filename))
                if entry.rom_uid is None:
                    log.warning("Plan target missing after scan collection=%s system=%s filename=%s",
                                collection_id, entry.system, entry.filename)

    def _apply_scrape_session(self, session_id, progress):
        session = self.scrape.sessions.get(str(session_id))
        applied, partial, failed = [], [], []
        touched_systems = set()
        selected = [item for item in session["items"] if self.scrape.proposal(item)]
        for index, item in enumerate(selected, start=1):
            progress(index - 1, max(1, len(selected)), item["filename"])
            proposal = self.scrape.proposal(item)
            if not proposal:
                continue
            # A media Apply rescans the Collection and may assign fresh rom_uid
            # values to every row. The session ID stays stable for review, but
            # writes must target the current row identified by system/file.
            target_rom_uid = None
            if session["target"] == "collection":
                current = self.workspace.open(session["collectionId"]).get_row_by_filename(
                    item["system"], item["filename"])
                if current is None:
                    message = "원본 Collection에서 스크랩 대상 게임을 찾을 수 없습니다."
                    item["status"] = "selected"
                    failed.append({"itemId": item["id"], "error": message,
                                   "fieldsApplied": [], "mediaApplied": []})
                    log.warning("Scraper target missing collection=%s sessionItem=%s system=%s filename=%s",
                                session["collectionId"], item["id"], item["system"], item["filename"])
                    continue
                target_rom_uid = current["rom_uid"]
                log.info("Scraper target resolved sessionItem=%s currentRomUid=%s system=%s filename=%s",
                         item["id"], target_rom_uid, item["system"], item["filename"])
            item_started = time.monotonic()
            log.info("Scraper apply start item=%s target=%s fields=%d media=%s",
                     item["id"], session["target"], len(proposal["fields"]),
                     [media.get("media_type") for media in proposal["media"]])
            applied_fields, applied_media, errors = {}, [], []
            fields_failed = False
            failed_media_indexes = []
            if proposal["fields"]:
                try:
                    if session["target"] == "archive":
                        result = self.archive_edit(item["id"], {**(item.get("fields") or {}),
                                                                **proposal["fields"]})
                    else:
                        result = self.save_fields(session["collectionId"], target_rom_uid,
                                                  proposal["fields"])
                    if not result.get("ok"):
                        raise ValueError(result.get("error"))
                    applied_fields = proposal["fields"]
                    log.info("Scraper metadata applied item=%s fields=%d seconds=%.3f",
                             item["id"], len(applied_fields), time.monotonic() - item_started)
                except Exception as exc:
                    fields_failed = True
                    errors.append(f"메타데이터: {exc}")
                    log.warning("Scraper metadata failed item=%s error=%s: %s",
                                item["id"], type(exc).__name__, exc)
            if proposal["media"]:
                if session["target"] == "archive" and not self._archive_config().get("mediaInternal"):
                    log.warning("Scraper media blocked item=%s target=archive mediaInternal=false",
                                item["id"])
                    failed_media_indexes.extend(item.get("selectedMedia") or [])
                    errors.append("미디어: Archive 내부 미디어 보관이 꺼져 있습니다.")
                else:
                    downloaded = []
                    selected_media = list(zip(item.get("selectedMedia") or [], proposal["media"]))
                    # Card previews load in WebView; Python has not downloaded
                    # them yet. Fetch independent media concurrently, then
                    # apply serially so Archive/Collection writes stay ordered.
                    with ThreadPoolExecutor(max_workers=min(3, len(selected_media) or 1)) as pool:
                        futures = [pool.submit(self._download_scrape_media, media["url"],
                                               session_id, item["id"], media["media_type"],
                                               media.get("format"))
                                   for _media_index, media in selected_media]
                        for number, ((media_index, media), future) in enumerate(
                                zip(selected_media, futures), start=1):
                            progress(index - 1, max(1, len(selected)),
                                     f'{item["filename"]} · 미디어 {number}/{len(selected_media)}')
                            try:
                                source_path = future.result()
                                if session["target"] == "archive":
                                    result = self.archive_media_paste(
                                        item["id"], media["media_type"],
                                        {"kind": "scraper", "path": source_path})
                                    if not result.get("ok"):
                                        raise ValueError(result.get("error"))
                                    applied_media.append(media)
                                    log.info("Scraper archive media applied item=%s type=%s",
                                             item["id"], media["media_type"])
                                else:
                                    downloaded.append((media_index, media, source_path))
                            except Exception as exc:
                                failed_media_indexes.append(media_index)
                                errors.append(f'{media.get("media_type") or "미디어"}: {exc}')
                                log.warning("Scraper media failed item=%s type=%s error=%s: %s",
                                            item["id"], media.get("media_type"), type(exc).__name__, exc)
                    if downloaded:
                        try:
                            touched_systems.update(self._apply_scraped_collection_media(
                                session["collectionId"], target_rom_uid,
                                [(media["media_type"], path) for _, media, path in downloaded]) or [])
                            applied_media.extend(media for _, media, _ in downloaded)
                            log.info("Scraper collection media applied item=%s types=%s",
                                     item["id"], [media["media_type"] for _, media, _ in downloaded])
                        except Exception as exc:
                            failed_media_indexes.extend(media_index for media_index, _, _ in downloaded)
                            errors.append(f"미디어 적용: {exc}")
                            log.warning("Scraper collection media failed item=%s error=%s: %s",
                                        item["id"], type(exc).__name__, exc)
            changed = bool(applied_fields or applied_media)
            if changed:
                provenance = proposal["provenance"]
                self.registry.add_scrape_provenance(
                    target_kind=session["target"], collection_id=session.get("collectionId"),
                    item_id=(target_rom_uid if target_rom_uid is not None else item["id"]),
                    provider=provenance["provider"],
                    remote_game_id=provenance["remoteGameId"], source_url=provenance["sourceUrl"],
                    evidence=provenance["evidence"], fields=applied_fields, media=applied_media)
                if not errors and provenance.get("remoteGameId"):
                    self.registry.set_scrape_confirmed_match(
                        target_kind=session["target"], collection_id=session.get("collectionId"),
                        system=item["system"], filename=item["filename"], size=item.get("size"),
                        provider=provenance["provider"],
                        remote_game_id=provenance["remoteGameId"])
                    system_id = _system_id(item.get("systemHint") or item["system"])
                    if system_id:
                        self.registry.set_scrape_query_alias(
                            provenance["provider"], system_id,
                            item.get("requestedQuery") or item["originalQuery"],
                            provenance["remoteGameId"])
            if errors:
                log.warning("Scraper apply item=%s target=%s failed: %s",
                            item["id"], session["target"], "; ".join(errors))
                item["selectedFields"] = (item.get("selectedFields") or []) if fields_failed else []
                item["selectedMedia"] = failed_media_indexes
                item["status"] = "selected"
                record = {"itemId": item["id"], "error": "; ".join(errors),
                          "fieldsApplied": list(applied_fields),
                          "mediaApplied": [media["media_type"] for media in applied_media]}
                (partial if changed else failed).append(record)
            else:
                item.update({"selectedCandidateId": None, "selectedFields": [],
                             "selectedMedia": [], "status": "applied"})
                applied.append(item["id"])
            log.info("Scraper apply end item=%s fieldsApplied=%d mediaApplied=%s errors=%d seconds=%.3f",
                     item["id"], len(applied_fields), [m["media_type"] for m in applied_media],
                     len(errors), time.monotonic() - item_started)
            progress(index, max(1, len(selected)), item["filename"])
        if touched_systems and session["target"] == "collection":
            systems = sorted(touched_systems)
            self.workspace.scan(session["collectionId"], force=True, systems=systems)
            self._rebind_plan_rows(session["collectionId"], systems)
        if not failed and not partial and all(
                item["status"] in ("applied", "skipped") for item in session["items"]):
            self.scrape.sessions.close(str(session_id))
        return {"applied": applied, "partial": partial, "failed": failed}

