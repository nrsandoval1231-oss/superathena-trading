from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

API_ROOT = "https://api.massive.com/v2/aggs/ticker"
TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _load_dotenv(path: Path) -> None:
    if not path.exists(): return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key and not key.lstrip().startswith("#"): os.environ.setdefault(key.strip(), value.strip())


def download_minute_bars(*, symbol: str, start: str, end: str, output_root: Path, adjusted: bool = False,
                         api_key: str | None = None, max_retries: int = 3, retry_backoff_seconds: float = 1.0) -> tuple[Path, Path]:
    """Download raw-preserving Massive minute bars for Athena Trading."""
    dotenv_candidates = [Path.cwd() / ".env", output_root / ".env", *output_root.parents]
    for candidate in dotenv_candidates:
        _load_dotenv(candidate / ".env" if candidate.is_dir() else candidate)
    key = api_key or os.environ.get("MASSIVE_API_KEY")
    if not key: raise RuntimeError("MASSIVE_API_KEY is not set. Add it to the local .env file.")
    if max_retries < 0 or retry_backoff_seconds < 0: raise ValueError("retry settings must be non-negative")
    snapshot_dir=output_root/"raw"/"massive"/"stocks"/"minute"; normalized_dir=output_root/"normalized"/"stocks"/"minute"; manifest_dir=output_root/"manifests"
    label=f"{symbol}_{start}_{end}".replace(":","-"); query={"adjusted":str(adjusted).lower(),"sort":"asc","limit":50000}
    base_url=f"{API_ROOT}/{symbol}/range/1/minute/{start}/{end}?{urlencode(query)}"; expected={"symbol":symbol,"start":start,"end":end,"adjusted":adjusted,"query":query}
    checkpoint_path=snapshot_dir/f"{label}.checkpoint.json"; state:dict[str,Any]={**expected,"pages":[],"next_url":_redact_url(base_url)}
    if checkpoint_path.exists():
        state=json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if any(state.get(k)!=v for k,v in expected.items()): raise ValueError("Massive checkpoint parameters do not match request")
    all_results=[]; seen=set(); previous=None; raw_pages=[]
    for page in state["pages"]:
        raw=(snapshot_dir/page["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=page["sha256"]: raise ValueError("Massive checkpoint raw page checksum mismatch")
        payload=_validate_response(raw); results=payload["results"]; _validate_timestamps(results,seen,previous)
        if results: previous=results[-1]["t"]
        all_results.extend(results); raw_pages.append({"file":page["file"],"sha256":page["sha256"],"row_count":len(results)})
    requests=set()
    while state.get("next_url"):
        request_url=str(state["next_url"]); identity=_redact_url(request_url)
        if identity in requests: raise RuntimeError("Massive cursor loop detected")
        requests.add(identity); raw,telemetry=_request_with_retry(_url_with_key(request_url,key),max_retries=max_retries,retry_backoff_seconds=retry_backoff_seconds)
        payload=_validate_response(raw); results=payload["results"]; _validate_timestamps(results,seen,previous)
        if results: previous=results[-1]["t"]
        next_url=_continuation(payload,base_url,query); page_no=len(state["pages"])+1; filename=f"{label}.page-{page_no:05d}.json"; snapshot_dir.mkdir(parents=True,exist_ok=True); (snapshot_dir/filename).write_bytes(raw)
        rec={"page":page_no,"file":filename,"sha256":hashlib.sha256(raw).hexdigest(),"row_count":len(results),"request":identity,"request_telemetry":telemetry,"next":_redact_url(next_url) if next_url else None}
        state["pages"].append(rec); state["next_url"]=_redact_url(next_url) if next_url else None; checkpoint_path.write_text(json.dumps(state,indent=2)+"\n",encoding="utf-8"); all_results.extend(results); raw_pages.append(rec)
    rows=_normalize_results(all_results,symbol=symbol,adjusted=adjusted); normalized_dir.mkdir(parents=True,exist_ok=True); manifest_dir.mkdir(parents=True,exist_ok=True)
    normalized_path=normalized_dir/f"{label}.jsonl"; normalized_path.write_text("\n".join(rows)+( "\n" if rows else ""),encoding="utf-8")
    manifest_path=manifest_dir/f"{label}.json"; manifest={"dataset_id":f"ATHENA-TRADING-DATA-{label}","symbol":symbol,"start":start,"end":end,"adjusted":adjusted,"provider":"Massive","source":"massive_stocks_aggregates_v2","retrieved_at":datetime.now(UTC).isoformat(),"row_count":len(rows),"normalized_path":str(normalized_path)}; manifest_path.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8"); return normalized_path,manifest_path


def _redact_url(url:str)->str:
    p=urlsplit(url); q=[(k,"[REDACTED]" if k.lower() in {"apikey","api_key"} else v) for k,v in parse_qsl(p.query,keep_blank_values=True)]; return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),p.fragment))
def _url_with_key(url:str,key:str)->str:
    p=urlsplit(url); q=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if k.lower() not in {"apikey","api_key"}]; q.append(("apiKey",key)); return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),p.fragment))
def _continuation(payload:dict[str,Any],base_url:str,query:dict[str,Any])->str|None:
    if payload.get("next_url"): return payload["next_url"]
    if payload.get("next_cursor"): return base_url+"&"+urlencode({"cursor":payload["next_cursor"]})
    return None
def _validate_timestamps(results:list[Any],seen:set[int],previous:int|None)->None:
    for bar in results:
        t=bar.get("t") if isinstance(bar,dict) else None
        if type(t) is not int or t<=0 or t in seen or (previous is not None and t<=previous): raise ValueError("Massive timestamps invalid, duplicate, or unordered")
        seen.add(t); previous=t
def _request_with_retry(url:str,*,max_retries:int,retry_backoff_seconds:float)->tuple[bytes,dict[str,int|float]]:
    started=time.monotonic()
    for attempt in range(max_retries+1):
        try:
            with urlopen(url,timeout=60) as response:
                return response.read(),{"attempt_count":attempt+1,"retry_count":attempt,"elapsed_seconds":round(time.monotonic()-started,6)}
        except HTTPError as exc:
            # Permanent 4xx (and any non-transient status) must fail fast: retrying
            # a 404 or 401 burns the budget and masks caller bugs.
            if getattr(exc, "code", None) not in TRANSIENT_HTTP_STATUSES:
                raise RuntimeError(f"Massive request failed with HTTP {exc.code}") from exc
            if attempt==max_retries: raise RuntimeError("Massive request failed after retries") from exc
        except URLError as exc:
            if attempt==max_retries: raise RuntimeError("Massive request failed after retries") from exc
        time.sleep(retry_backoff_seconds*(2**attempt))
    raise AssertionError
def _validate_response(raw:bytes)->dict[str,Any]:
    payload=json.loads(raw)
    if not isinstance(payload,dict) or payload.get("status") not in ("OK","DELAYED") or not isinstance(payload.get("results"),list): raise ValueError("Massive response invalid")
    return payload
def _normalize_results(results:list[Any],*,symbol:str,adjusted:bool)->list[str]:
    rows=[]
    for bar in results:
        t=int(bar["t"]); event_at=datetime.fromtimestamp(t/1000,tz=UTC); row={"symbol":symbol,"event_at":event_at.isoformat(),"available_at":(event_at+timedelta(minutes=1)).isoformat(),"open":bar.get("o"),"high":bar.get("h"),"low":bar.get("l"),"close":bar.get("c"),"volume":bar.get("v"),"vwap":bar.get("vw"),"transactions":bar.get("n"),"source":"massive_stocks_aggregates_v2","adjusted":adjusted}; rows.append(json.dumps(row,separators=(",",":")))
    return rows
