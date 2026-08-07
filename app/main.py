from __future__ import annotations

from datetime import date, datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import HTTPException
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.clients.api_football import ApiFootballClient, ApiFootballError
from app.config import BASE_DIR, get_settings
from app.database.store import Store
from app.services.analysis_service import AnalysisService
from app.services.fixture_service import FixtureService
from app.services.performance_service import metrics
from app.validation.backtest import professional_metrics
from app.services.scanner_service import ScannerConfigurationError, ScannerService
from app.intelligence.monte_carlo import simulate
from app.intelligence.data_quality import assess as assess_data_quality
from app.intelligence.reliability import summarize as reliability_summary
from app.intelligence.confidence import dynamic as dynamic_confidence
from app.intelligence.audit import build as build_audit
from app.intelligence.drift import compare as compare_drift
from app.automation.engine import AutomationEngine
from app.settlement import SettlementQueueService
from app.admin.settings import TOP_LEAGUE_PRESETS
from app.access_control import AccessPolicy, Permission
from app.services.decision_view_service import DecisionViewService
from app.timezone_utils import today_wita_iso
from app.decision_policy import best_market_from_analysis, recommendation_from_analysis
import json
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

settings = get_settings()
client = ApiFootballClient(settings)
store = Store(settings.resolved_database_url)
store.ensure_admin_user(settings.admin_username, settings.admin_password)
settlement_queue = SettlementQueueService(store)
automation_engine = AutomationEngine(client, store, interval_minutes=settings.settlement_interval_minutes)

@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.automation_enabled:
        automation_engine.start()
    yield
    await automation_engine.stop()

app = FastAPI(title=settings.app_name, version="12.0.0-core-engine-unification", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
fixture_service = FixtureService(client)
analysis_service = AnalysisService(client, store)
scanner_service = ScannerService(client, store)
decision_view_service = DecisionViewService()


def current_user(request: Request) -> dict | None:
    """Return the active database user and upgrade legacy sessions in-place.

    Deployments before v7 stored only ``authenticated``/``username`` in the
    session.  Without this compatibility bridge an already logged-in admin did
    not receive ``user_id`` or ``role``, so the Membership menu disappeared.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        legacy_username = str(request.session.get("username") or "").strip()
        if request.session.get("authenticated") and legacy_username:
            legacy_user = store.user_by_username(legacy_username)
            if legacy_user:
                request.session.update({
                    "user_id": int(legacy_user["id"]),
                    "username": legacy_user["username"],
                    "role": legacy_user["role"],
                })
                user_id = legacy_user["id"]
        if not user_id:
            return None
    user = store.refresh_membership_status(int(user_id))
    if not user or str(user.get("status") or "").upper() != "ACTIVE":
        request.session.clear()
        return None
    if str(user.get("role") or "MEMBER").upper() == "MEMBER":
        license_row = store.license_for_user(int(user_id))
        if not license_row or str(license_row.get("status") or "").upper() != "ACTIVE":
            request.session.clear()
            return None
    # Keep the session synchronized after an administrator changes a role.
    request.session["username"] = user.get("username")
    request.session["role"] = user.get("role")
    return user


def auth(request: Request) -> bool:
    return current_user(request) is not None


def is_admin(request: Request) -> bool:
    return AccessPolicy.allows(current_user(request), Permission.MANAGE_SETTINGS)


def require_permission(request: Request, permission: Permission) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not AccessPolicy.allows(user, permission):
        raise HTTPException(status_code=403, detail="Fitur ini hanya tersedia untuk Administrator.")
    return user


def login_redirect(reason: str | None = None) -> RedirectResponse:
    from urllib.parse import quote
    target = "/login" if not reason else f"/login?error={quote(reason)}"
    return RedirectResponse(target, status_code=303)


def ctx(request: Request, **kwargs):
    user = current_user(request)
    permission_flags = AccessPolicy.template_flags(user)
    return {
        "app_name": settings.app_name,
        "username": user.get("username") if user else "",
        "current_user": user,
        "user_role": str(user.get("role") or "").upper() if user else "",
        "is_admin_user": AccessPolicy.allows(user, Permission.MANAGE_SETTINGS),
        "permissions": permission_flags,
        **permission_flags,
        **kwargs,
    }


@app.exception_handler(HTTPException)
async def app_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 403 and "text/html" in request.headers.get("accept", "text/html"):
        return templates.TemplateResponse(
            request=request, name="access_denied.html", context=ctx(request), status_code=403
        )
    if exc.status_code == 401:
        return login_redirect("Silakan login terlebih dahulu.")
    return await http_exception_handler(request, exc)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": settings.app_name, "version": "12.1.0-engine-stabilization", "api_football_configured": settings.api_configured, "database": "ready", "quota": client.quota_status()}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    if auth(request): return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"app_name": settings.app_name, "error": error})


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user, error = store.authenticate_user(username, password)
    if user:
        request.session.clear()
        request.session.update({
            "authenticated": True,
            "user_id": int(user["id"]),
            "username": user["username"],
            "role": user["role"],
        })
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"app_name": settings.app_name, "error": error}, status_code=401)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear(); return login_redirect()


def _today_pick_rows(day: str) -> list[dict]:
    """Read the authoritative decision_records snapshot only."""
    rows = store.decision_records_for_date(day)
    prepared: list[dict] = []
    for row in rows:
        published = bool(row.get("published"))
        probability_pct = row.get("recommendation_probability_pct") if published else row.get("best_market_probability_pct")
        label = row.get("recommendation_label") if published else row.get("best_market_label")
        ev_raw = row.get("ev") if published else None
        ev_pct = float(ev_raw or 0) * 100 if abs(float(ev_raw or 0)) <= 1 else float(ev_raw or 0)
        builder = row.get("builder") if row.get("builder_available") and published else None
        prepared.append({
            **row,
            "status": row.get("final_tier") or "NO_BET",
            "decision_label": row.get("final_label") or "NO BET",
            "pick": label or "NO MARKET",
            "probability_pct": round(float(probability_pct or 0), 1),
            "agreement": float(row.get("model_agreement") or 0),
            "pqi": float(row.get("data_quality") or 0),
            "health": float(row.get("reliability_score") or 0),
            "combined": float(row.get("confidence") or 0),
            "ev_pct": round(ev_pct, 1),
            "best_builder": builder,
            "builder_status": row.get("builder_status") or "NO_QUALIFIED_BUILDER",
            "settlement_eligible": published,
        })
    return prepared

@app.get("/", response_class=HTMLResponse)
async def today_picks(request: Request, pick_date: str | None = None):
    if not auth(request): return login_redirect()
    selected_date = pick_date or today_wita_iso()
    rows = _today_pick_rows(selected_date)
    group_names = ("ELITE_PICK", "STRONG_PICK", "PICK", "MONITOR", "NO_BET")
    groups = {name: [r for r in rows if r["status"] == name] for name in group_names}
    selected_candidates = groups["ELITE_PICK"] or groups["STRONG_PICK"] or groups["PICK"]
    selected_pick = selected_candidates[0] if selected_candidates else None

    # Builder is a dependent output of the selected decision, never a separate
    # cross-fixture recommendation. If the selected fixture has no qualified
    # builder, the daily page explicitly shows no builder.
    best_builder = None
    if selected_pick and selected_pick.get("best_builder"):
        builder = dict(selected_pick["best_builder"])
        quality = float(builder.get("builder_quality") or 0)
        probability = float(builder.get("probability_pct") or 0)
        if quality >= 75 and probability >= 55:
            builder["fixture_id"] = selected_pick.get("fixture_id")
            builder["home_team"] = selected_pick.get("home_team")
            builder["away_team"] = selected_pick.get("away_team")
            builder["decision_status"] = selected_pick.get("status")
            best_builder = builder

    counts = {name: len(groups[name]) for name in group_names}
    if selected_pick:
        daily_brief = (
            f"Scanner telah menghasilkan {len(rows)} keputusan. Selected Pick tersedia pada "
            f"{selected_pick.get('home_team') or 'Tim kandang'} vs {selected_pick.get('away_team') or 'Tim tandang'} dengan status "
            f"{str(selected_pick.get('status') or 'PICK').replace('_', ' ').title()}."
        )
    elif rows:
        daily_brief = (
            f"Sebanyak {len(rows)} keputusan tersimpan, tetapi belum ada pertandingan yang lolos "
            "seluruh kualifikasi rekomendasi. Pertandingan tetap tersedia sebagai Best Market/Monitor untuk audit."
        )
    else:
        daily_brief = "Belum ada hasil scanner untuk tanggal ini. Jalankan scanner secara batch dari menu Scanner."

    perf = metrics(store.recent_predictions(), store.trades(), settings.paper_bankroll)
    return templates.TemplateResponse(request=request, name="today_picks.html", context=ctx(
        request, selected_date=selected_date, rows=rows, groups=groups, counts=counts,
        selected_pick=selected_pick, best_builder=best_builder, performance=perf,
        daily_brief=daily_brief,
    ))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not auth(request): return login_redirect()
    intelligence = store.performance_intelligence_dashboard()
    overall = intelligence.get("overall") or {}
    score = intelligence.get("score") or {}
    perf = {
        "predictions": int(overall.get("sample") or 0),
        "accuracy": round(float(overall.get("accuracy") or 0), 1),
        "profit": round(float(overall.get("profit") or 0), 2),
        "roi": round(float(overall.get("roi") or 0), 1),
        "yield": round(float(overall.get("yield_pct") or 0), 1),
        "grade": score.get("grade") or "D",
    }
    return templates.TemplateResponse(request=request, name="dashboard.html", context=ctx(request, api_configured=settings.api_configured, today=today_wita_iso(), performance=perf))


def _decode_prediction_payload(row: dict | None) -> dict:
    if not row:
        return {}
    try:
        payload = json.loads(row.get("payload") or "{}")
        return payload if isinstance(payload, dict) else {}
    except (TypeError, ValueError):
        return {}


def _stored_analysis_for_fixture(fixture_id: int) -> tuple[dict | None, dict | None]:
    decision_record = store.latest_decision_record(fixture_id)
    if decision_record and isinstance(decision_record.get("analysis"), dict):
        return decision_record, decision_record.get("analysis")
    row = store.latest_prediction_by_fixture(fixture_id)
    payload = _decode_prediction_payload(row)
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else None
    return row, analysis


def _stored_match_groups(day: str) -> list[dict]:
    rows = store.stored_matches_for_date(day)
    grouped: dict[str, dict] = {}
    seen: set[int] = set()
    for row in rows:
        fixture_id = int(row.get("fixture_id") or 0)
        if not fixture_id or fixture_id in seen:
            continue
        seen.add(fixture_id)
        league = str(row.get("league") or "Stored Analysis")
        group = grouped.setdefault(league, {
            "league": {"name": league, "country": "Database", "logo": None},
            "fixtures": [],
        })
        payload = _decode_prediction_payload(row)
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
        fx = analysis.get("fixture") if isinstance(analysis, dict) else {}
        fixture = (fx or {}).get("fixture") or {}
        teams = (fx or {}).get("teams") or {}
        group["fixtures"].append({
            "fixture": {
                "id": fixture_id,
                "date": fixture.get("date") or row.get("fixture_date") or row.get("created_at"),
                "status": {"short": row.get("fixture_status") or "SAVED"},
            },
            "teams": {
                "home": {"name": row.get("home_team") or "Home", "logo": ((teams.get("home") or {}).get("logo"))},
                "away": {"name": row.get("away_team") or "Away", "logo": ((teams.get("away") or {}).get("logo"))},
            },
            "goals": {"home": row.get("home_score"), "away": row.get("away_score")},
            "stored": True,
        })
    return list(grouped.values())


@app.get("/matches", response_class=HTMLResponse)
async def matches(request: Request, match_date: str | None = None):
    if not auth(request):
        return login_redirect()
    require_permission(request, Permission.VIEW_SAVED_MATCHES)
    selected = match_date or today_wita_iso()
    error = None
    user = current_user(request)
    if AccessPolicy.allows(user, Permission.VIEW_LIVE_API_MATCHES):
        try:
            groups, paging = await fixture_service.grouped_fixtures(selected)
        except ApiFootballError as exc:
            error = str(exc)
            groups, paging = _stored_match_groups(selected), {}
    else:
        groups, paging = _stored_match_groups(selected), {}
    return templates.TemplateResponse(
        request=request,
        name="matches.html",
        context=ctx(request, selected_date=selected, groups=groups, error=error, paging=paging),
    )


@app.get("/match/{fixture_id}", response_class=HTMLResponse)
async def match_detail(request: Request, fixture_id: int):
    """Read-only match analysis for every authenticated role. Never calls API-Football."""
    if not auth(request):
        return login_redirect()
    require_permission(request, Permission.VIEW_RESULTS)
    row, analysis = _stored_analysis_for_fixture(fixture_id)
    if analysis:
        analysis, _ = decision_view_service.normalize(analysis)
        return templates.TemplateResponse(
            request=request,
            name="match_detail.html",
            context=ctx(request, analysis=analysis, error=None, stored_prediction=row, read_only=True),
        )
    if row:
        return templates.TemplateResponse(
            request=request,
            name="saved_match_detail.html",
            context=ctx(request, prediction=row, payload=_decode_prediction_payload(row), error=None, read_only=True),
        )
    return templates.TemplateResponse(
        request=request,
        name="saved_match_detail.html",
        context=ctx(
            request, prediction=None, payload={},
            error="Analisis tersimpan belum tersedia. Administrator perlu menjalankan refresh analisis.",
            read_only=True, fixture_id=fixture_id,
        ),
        status_code=404,
    )


@app.post("/match/{fixture_id}/refresh", response_class=HTMLResponse)
async def refresh_match_analysis(request: Request, fixture_id: int):
    """Administrator-only write route: fetch, recompute and persist a match analysis."""
    if not auth(request):
        return login_redirect()
    require_permission(request, Permission.REFRESH_MATCH_ANALYSIS)
    try:
        raw_analysis = await analysis_service.full(fixture_id)
        analysis, decision_contract = decision_view_service.normalize(raw_analysis)
        fx = analysis.get("fixture") or {}
        recommendation = recommendation_from_analysis(analysis)
        best_market = best_market_from_analysis(analysis)
        best = recommendation or best_market
        probability = best.get("probability")
        if probability is None and best.get("probability_pct") is not None:
            probability = float(best["probability_pct"]) / 100.0
        fixture_info = fx.get("fixture") or {}
        store.save_prediction({
            "fixture_id": fixture_id,
            "league": (fx.get("league") or {}).get("name") or "Unknown League",
            "home_team": ((fx.get("teams") or {}).get("home") or {}).get("name") or "Home",
            "away_team": ((fx.get("teams") or {}).get("away") or {}).get("name") or "Away",
            "pick": best.get("label") or "NO MARKET",
            "market_key": best.get("key"),
            "pick_role": str((recommendation or {}).get("decision_tier") or "NO_BET"),
            "settlement_eligible": bool(recommendation),
            "confidence": (analysis.get("internal") or {}).get("confidence"),
            "probability": probability,
            "odds": best.get("odds"),
            "ev": best.get("ev"),
            "analysis": analysis,
            "pqi": ((analysis.get("internal") or {}).get("quality") or {}).get("score"),
            "fixture_date": fixture_info.get("date"),
            "fixture_status": (fixture_info.get("status") or {}).get("short"),
            "source": "ADMIN_REFRESH",
            "best_builder": analysis.get("best_builder"),
            "builder_diagnostics": analysis.get("builder_diagnostics") or {},
        })
        store.save_odds_snapshot(fixture_id, analysis.get("markets") or [])
        return RedirectResponse(f"/match/{fixture_id}", status_code=303)
    except ApiFootballError as exc:
        return RedirectResponse(f"/match/{fixture_id}?refresh_error={quote(str(exc))}", status_code=303)
    except Exception as exc:
        logger.exception("Refresh match analysis gagal untuk fixture_id=%s", fixture_id)
        return RedirectResponse(
            f"/match/{fixture_id}?refresh_error={quote(exc.__class__.__name__)}", status_code=303
        )


def _empty_scan_data() -> dict:
    return {"rows": [], "best_picks": [], "safe_picks": [], "balanced_picks": [], "value_picks": [],
            "backtest_rows": [], "backtest_summary": {"total":0,"wins":0,"losses":0,"voids":0,"hit_rate":0.0,"profit":0.0},
            "settled_count":0, "excluded_started":0, "upcoming_count":0, "total_upcoming":0,
            "already_scanned":0, "remaining":0, "failed_count":0, "scanner_settings":store.settings(),
            "preview_only":True, "quota_paused":False, "quota_status":client.quota_status()}


@app.get("/scanner", response_class=HTMLResponse)
async def scanner(request: Request, scan_date: str | None = None):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.RUN_SCANNER)
    selected = scan_date or today_wita_iso()
    scan_data = _empty_scan_data(); error = None
    try:
        scan_data = await scanner_service.preview(selected)
    except (ApiFootballError, ScannerConfigurationError) as exc:
        error = str(exc)
    except Exception as exc:
        logger.exception("Scanner preview gagal untuk tanggal %s", selected)
        error = f"Preview scanner gagal: {exc.__class__.__name__}."
    return templates.TemplateResponse(request=request, name="scanner.html", context=ctx(request, selected_date=selected, error=error, **scan_data))


@app.post("/scanner/run", response_class=HTMLResponse)
async def scanner_run(request: Request, scan_date: str = Form(...)):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.RUN_SCANNER)
    scan_data = _empty_scan_data(); error = None
    try:
        scan_data = await scanner_service.scan(scan_date)
    except (ApiFootballError, ScannerConfigurationError) as exc:
        error = str(exc)
    except Exception as exc:
        logger.exception("Scanner gagal untuk tanggal %s", scan_date)
        error = f"Scanner gagal diproses: {exc.__class__.__name__}. Periksa log Render lalu lanjutkan batch."
    return templates.TemplateResponse(request=request, name="scanner.html", context=ctx(request, selected_date=scan_date, error=error, **scan_data))


@app.get("/predictions", response_class=HTMLResponse)
async def predictions(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    result: str = "ALL",
    fixture_status: str = "ALL",
    search: str | None = None,
):
    if not auth(request): return login_redirect()
    rows = store.prediction_history(
        date_from=date_from, date_to=date_to, result=result,
        fixture_status=fixture_status, search=search, limit=1000,
    )
    today_wita = today_wita_iso()
    for row in rows:
        fixture_day = str(row.get("fixture_date") or "")[:10]
        status = str(row.get("fixture_status") or "UNKNOWN").upper()
        stored_reason = str(row.get("settlement_reason") or "").strip()
        state = str(row.get("settlement_state") or "PENDING").upper()
        settlement_eligible = bool(row.get("settlement_eligible", 1))
        row["settlement_eligible"] = settlement_eligible
        if str(row.get("result") or "PENDING").upper() != "PENDING":
            reason = "Settlement selesai"
        elif not settlement_eligible or state == "NOT_APPLICABLE":
            reason = "Observasi model; bukan rekomendasi untuk settlement"
            state = "NOT_APPLICABLE"
        elif state == "NEEDS_INVESTIGATION":
            reason = stored_reason or "Perlu pemeriksaan manual"
        elif stored_reason:
            reason = stored_reason
        elif not row.get("fixture_id"):
            reason = "Fixture ID tidak tersedia"
        elif status in {"FT", "AET", "PEN", "AWD", "WO", "CANC", "ABD", "SUSP", "INT"}:
            reason = "Status final; menunggu evaluasi ulang"
        elif status == "NOT_FOUND":
            reason = "Fixture tidak ditemukan API"
        elif status == "API_ERROR":
            reason = "Pemeriksaan API terakhir gagal"
        elif fixture_day and fixture_day < today_wita:
            reason = "Overdue; masuk antrean recovery"
        else:
            reason = "Belum final"
        row["settlement_reason"] = reason
        row["settlement_state"] = state
        row["is_overdue"] = bool(settlement_eligible and row.get("result") == "PENDING" and fixture_day and fixture_day < today_wita)
    queue_snapshot = settlement_queue.build()
    queue_by_prediction = {int(item["id"]): item.get("queue_bucket") for bucket in (queue_snapshot.ready, queue_snapshot.waiting, queue_snapshot.recovery, queue_snapshot.investigation) for item in bucket}
    for row in rows:
        row["queue_bucket"] = queue_by_prediction.get(int(row.get("id") or 0), "SETTLED")
    return templates.TemplateResponse(request=request, name="predictions.html", context=ctx(
        request, rows=rows, summary=queue_snapshot.summary(), today_wita=today_wita,
        filters={"date_from":date_from or "", "date_to":date_to or "", "result":result,
                 "fixture_status":fixture_status, "search":search or ""},
    ))


@app.get("/bet-builder", response_class=HTMLResponse)
async def bet_builder(request: Request):
    if not auth(request): return login_redirect()
    records = store.decision_records_for_date(today_wita_iso(), 2000)
    builder_rows = []
    diagnostic_rows = []
    for row in records:
        builder = row.get("builder") if row.get("builder_available") else None
        analysis = row.get("analysis") or {}
        portfolio = row.get("builder_portfolio") or analysis.get("builder_portfolio") or ([] if not builder else [builder])
        diagnostics = analysis.get("builder_diagnostics") or (builder or {}).get("diagnostics") or {}
        base = {
            "fixture_id": row.get("fixture_id"), "fixture_date": row.get("fixture_date"),
            "league": row.get("league"), "home_team": row.get("home_team"),
            "away_team": row.get("away_team"), "pick": row.get("recommendation_label") or row.get("best_market_label"),
            "decision_status": row.get("final_tier"),
        }
        if isinstance(portfolio, list):
            for portfolio_builder in portfolio[:3]:
                if isinstance(portfolio_builder, dict) and portfolio_builder.get("selections"):
                    builder_rows.append({**base, **portfolio_builder})
        if diagnostics:
            diagnostic_rows.append({**base, "diagnostics": diagnostics, "has_builder": bool(builder)})
    return templates.TemplateResponse(request=request, name="bet_builder.html", context=ctx(
        request, builder_rows=builder_rows[:50], diagnostic_rows=diagnostic_rows[:100],
        total_predictions=len(records), builders_found=len(builder_rows),
    ))


@app.get("/backtesting", response_class=HTMLResponse)
async def backtesting(request: Request):
    if not auth(request): return login_redirect()
    rows=store.recent_predictions(1000); perf=metrics(rows, store.trades(), settings.paper_bankroll); pro=professional_metrics(rows)
    return templates.TemplateResponse(request=request, name="backtesting.html", context=ctx(request, rows=rows, performance=perf, professional=pro))


@app.get("/performance", response_class=HTMLResponse)
async def performance(request: Request):
    if not auth(request): return login_redirect()
    intelligence = store.performance_intelligence_dashboard()
    return templates.TemplateResponse(request=request, name="performance.html", context=ctx(request, intelligence=intelligence))


@app.get("/paper-trading", response_class=HTMLResponse)
async def paper_trading(request: Request):
    if not auth(request): return login_redirect()
    trades=store.trades(); perf=metrics(store.recent_predictions(), trades, settings.paper_bankroll)
    return templates.TemplateResponse(request=request, name="paper_trading.html", context=ctx(request, trades=trades, performance=perf))


@app.post("/paper-trading/add")
async def add_trade(request: Request, fixture_id: int=Form(...), description: str=Form(...), odds: float=Form(...), stake: float=Form(...)):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_TRADES)
    store.add_trade(fixture_id, description, odds, stake)
    return RedirectResponse("/paper-trading", status_code=303)


@app.post("/paper-trading/{trade_id}/settle")
async def settle_trade(request: Request, trade_id: int, result: str=Form(...)):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_TRADES)
    store.settle_trade(trade_id, result)
    return RedirectResponse("/paper-trading", status_code=303)


@app.post("/predictions/{prediction_id}/settle")
async def settle_prediction(request: Request, prediction_id: int, result: str=Form(...)):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.RUN_SETTLEMENT)
    store.settle_prediction(prediction_id, result)
    return RedirectResponse("/predictions", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, message: str | None = None, error: str | None = None):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_SETTINGS)
    return templates.TemplateResponse(request=request, name="admin.html", context=ctx(
        request, settings_values=store.settings(), quota=client.quota_status(),
        api_configured=settings.api_configured, database_status=store.database_status(),
        top_league_presets=TOP_LEAGUE_PRESETS, message=message, error=error,
    ))


@app.post("/admin/settings")
async def admin_settings(
    request: Request, min_confidence: float=Form(...), min_pqi: float=Form(...),
    min_ev: float=Form(...), max_builder_legs: int=Form(...), kelly_fraction: float=Form(...),
    scanner_limit: int=Form(...), scanner_profile: str=Form("SAFE"),
    scanner_concurrency: int=Form(2), scanner_retry: int=Form(2),
    scanner_delay_seconds: float=Form(0.5), scanner_timeout_seconds: int=Form(50),
    scanner_skip_existing: bool=Form(False),
    scanner_league_filter_mode: str=Form("SELECTED"),
    scanner_league_filter_enabled: bool=Form(False),
    scanner_league_ids: list[int]=Form([]),
    scanner_custom_league_ids: str=Form(""),
):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_SETTINGS)
    profile = scanner_profile.upper().strip()
    presets = {
        "SAFE": {"scanner_concurrency": 1, "scanner_retry": 3, "scanner_delay_seconds": 1.0},
        "BALANCED": {"scanner_concurrency": 2, "scanner_retry": 2, "scanner_delay_seconds": 0.5},
        "FAST": {"scanner_concurrency": 4, "scanner_retry": 1, "scanner_delay_seconds": 0.0},
    }
    scanner_values = presets.get(profile, {
        "scanner_concurrency": max(1, min(scanner_concurrency, 4)),
        "scanner_retry": max(0, min(scanner_retry, 5)),
        "scanner_delay_seconds": max(0.0, min(scanner_delay_seconds, 10.0)),
    })
    custom_ids: list[int] = []
    for token in scanner_custom_league_ids.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            custom_ids.append(int(token))
        except ValueError:
            continue
    allowed_league_ids = sorted(set(scanner_league_ids + custom_ids))
    league_filter_mode = str(scanner_league_filter_mode or "SELECTED").upper().strip()
    if league_filter_mode not in {"ALL", "SELECTED"}:
        league_filter_mode = "SELECTED"
    league_filter_enabled = league_filter_mode == "SELECTED"
    if league_filter_enabled and not allowed_league_ids:
        from urllib.parse import quote
        msg = quote("Tidak ada liga yang dipilih. Pilih minimal satu liga atau gunakan mode Semua negara & semua liga.")
        return RedirectResponse(f"/admin?error={msg}", status_code=303)

    store.update_settings({
        "min_confidence":min_confidence,"min_pqi":min_pqi,"min_ev":min_ev,
        "max_builder_legs":min(max_builder_legs, 2),"kelly_fraction":kelly_fraction,
        "scanner_profile":profile if profile in {"SAFE","BALANCED","FAST","CUSTOM"} else "CUSTOM",
        "scanner_limit":10,
        **scanner_values,
        "scanner_timeout_seconds":max(15,min(scanner_timeout_seconds,60)),
        "scanner_skip_existing":bool(scanner_skip_existing),
        "scanner_league_filter_mode":league_filter_mode,
        "scanner_league_filter_enabled":league_filter_enabled,
        "scanner_allowed_league_ids":allowed_league_ids,
    })
    return RedirectResponse("/admin?message=Pengaturan+Scanner+berhasil+disimpan", status_code=303)


@app.get("/members", response_class=HTMLResponse)
async def members_page(request: Request, message: str | None = None, error: str | None = None,
                       q: str | None = None, status: str | None = None,
                       role: str | None = None, expiry: str | None = None):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    users = store.list_users(query=q, status=status, role=role, expiry=expiry)
    summary = store.membership_summary()
    filters = {"q": q or "", "status": status or "", "role": role or "", "expiry": expiry or ""}
    return templates.TemplateResponse(request=request, name="members.html",
        context=ctx(request, users=users, summary=summary, filters=filters, message=message, error=error))


@app.get("/members/{user_id}", response_class=HTMLResponse)
async def member_detail(request: Request, user_id: int, message: str | None = None, error: str | None = None):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    user = store.refresh_membership_status(user_id)
    if not user:
        return RedirectResponse("/members?error=" + quote("Akun tidak ditemukan."), status_code=303)
    expiry = store._as_utc(user.get("membership_expires_at"))
    now = datetime.now(timezone.utc)
    if expiry and str(user.get("role") or "MEMBER").upper() == "MEMBER":
        seconds = (expiry - now).total_seconds()
        user["days_remaining"] = max(0, int((seconds + 86399) // 86400))
    else:
        user["days_remaining"] = None
    history = store.membership_history_detailed(user_id)
    # License UI must use the same database source as generate/rotate/status routes.
    # Previously the template received no license_record, so it always rendered
    # "belum memiliki license" even when the backend had already created one.
    license_record = store.license_for_user(user_id)
    license_history = store.license_history_detailed(user_id)
    license_view = {
        "has_license": bool(license_record),
        "status": str((license_record or {}).get("status") or "MISSING").upper(),
        "can_generate": license_record is None,
        "can_rotate": license_record is not None,
        "can_activate": bool(license_record) and str(license_record.get("status") or "").upper() == "DISABLED",
        "can_disable": bool(license_record) and str(license_record.get("status") or "").upper() == "ACTIVE",
        "can_revoke": bool(license_record) and str(license_record.get("status") or "").upper() != "REVOKED",
    }
    return templates.TemplateResponse(request=request, name="member_detail.html",
        context=ctx(request, member=user, history=history, license_record=license_record,
                    license_history=license_history, license_view=license_view,
                    message=message, error=error))


@app.post("/members/create")
async def member_create(request: Request, username: str=Form(...), full_name: str=Form(""), password: str=Form(...), role: str=Form("MEMBER"), membership_expires_at: str=Form("")):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    try:
        expiry = datetime.fromisoformat(membership_expires_at).replace(tzinfo=timezone.utc) if membership_expires_at else None
        user_id = store.create_user(username=username, full_name=full_name, password=password, role=role,
            membership_started_at=datetime.now(timezone.utc), membership_expires_at=expiry,
            changed_by=int(request.session["user_id"]))
        return RedirectResponse(f"/members/{user_id}?message=" + quote("Member berhasil dibuat."), status_code=303)
    except Exception as exc:
        return RedirectResponse("/members?error=" + quote(str(exc)), status_code=303)


@app.post("/members/{user_id}/edit")
async def member_edit(request: Request, user_id: int, full_name: str=Form(""), role: str=Form("MEMBER"),
                      membership_expires_at: str=Form(""), note: str=Form("")):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    try:
        expiry = datetime.fromisoformat(membership_expires_at).replace(tzinfo=timezone.utc) if membership_expires_at else None
        store.update_user_profile(user_id, full_name=full_name, role=role,
            membership_expires_at=expiry, changed_by=int(request.session["user_id"]), note=note or None)
        return RedirectResponse(f"/members/{user_id}?message=" + quote("Data akun berhasil diperbarui."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)


@app.post("/members/{user_id}/extend")
async def member_extend(request: Request, user_id: int, membership_expires_at: str=Form(...), note: str=Form("")):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    try:
        expiry = datetime.fromisoformat(membership_expires_at).replace(tzinfo=timezone.utc)
        store.extend_membership(user_id, expiry, changed_by=int(request.session["user_id"]), note=note or None)
        return RedirectResponse(f"/members/{user_id}?message=" + quote("Masa aktif berhasil diperpanjang."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)


@app.post("/members/{user_id}/extend-days")
async def member_extend_days(request: Request, user_id: int, days: int=Form(...), note: str=Form("")):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    try:
        store.extend_membership_days(user_id, days, changed_by=int(request.session["user_id"]), note=note or None)
        return RedirectResponse(f"/members/{user_id}?message=" + quote(f"Masa aktif ditambah {days} hari."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)


@app.post("/members/{user_id}/status")
async def member_status(request: Request, user_id: int, status: str=Form(...)):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    try:
        store.set_user_status(user_id, status, changed_by=int(request.session["user_id"]))
        return RedirectResponse(f"/members/{user_id}?message=" + quote("Status akun berhasil diperbarui."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)


@app.post("/members/{user_id}/reset-password")
async def member_reset_password(request: Request, user_id: int, new_password: str=Form(...)):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    try:
        store.reset_user_password(user_id, new_password, changed_by=int(request.session["user_id"]))
        return RedirectResponse(f"/members/{user_id}?message=" + quote("Password member berhasil direset."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)


@app.post("/members/{user_id}/delete")
async def member_delete(request: Request, user_id: int):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_MEMBERS)
    try:
        store.delete_user(user_id, changed_by=int(request.session["user_id"]))
        return RedirectResponse("/members?message=" + quote("Akun berhasil dihapus permanen."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)



@app.post("/members/{user_id}/license/generate")
async def member_license_generate(request: Request, user_id: int):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_LICENSES)
    try:
        store.create_user_license(user_id, changed_by=int(request.session["user_id"]))
        return RedirectResponse(f"/members/{user_id}?message=" + quote("License pertama berhasil dibuat."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)

@app.post("/members/{user_id}/license/rotate")
async def member_license_rotate(request: Request, user_id: int, note: str=Form("")):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_LICENSES)
    try:
        store.rotate_user_license(user_id, changed_by=int(request.session["user_id"]), note=note or None)
        return RedirectResponse(f"/members/{user_id}?message=" + quote("License berhasil diganti. License lama tidak berlaku."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)

@app.post("/members/{user_id}/license/status")
async def member_license_status(request: Request, user_id: int, status: str=Form(...), note: str=Form("")):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.MANAGE_LICENSES)
    try:
        store.set_license_status(user_id, status, changed_by=int(request.session["user_id"]), note=note or None)
        return RedirectResponse(f"/members/{user_id}?message=" + quote("Status license berhasil diperbarui."), status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/members/{user_id}?error=" + quote(str(exc)), status_code=303)

@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request, message: str | None = None, error: str | None = None):
    if not auth(request): return login_redirect()
    return templates.TemplateResponse(request=request, name="account.html", context=ctx(request, message=message, error=error))


@app.post("/account/password")
async def account_password(request: Request, current_password: str=Form(...), new_password: str=Form(...)):
    if not auth(request): return login_redirect()
    from urllib.parse import quote
    try:
        store.change_own_password(int(request.session["user_id"]), current_password, new_password)
        return RedirectResponse("/account?message=" + quote("Password berhasil diubah."), status_code=303)
    except Exception as exc:
        return RedirectResponse("/account?error=" + quote(str(exc)), status_code=303)


@app.get("/intelligence", response_class=HTMLResponse)
async def intelligence_lab(request: Request, prediction_id: int | None = None):
    if not auth(request): return login_redirect()
    row=None; audit={}; monte={}; dynamic={}; drift={}; error=None
    if prediction_id:
        row=store.prediction_by_id(prediction_id)
        if not row: error="Prediction ID tidak ditemukan."
        else:
            try:
                payload=json.loads(row.get("payload") or "{}")
                analysis=payload.get("analysis") or payload
                internal=analysis.get("internal",{})
                monte=analysis.get("monte_carlo") or simulate(float(internal.get("home_xg",1.2)),float(internal.get("away_xg",1.0)),20000,int(row["fixture_id"]))
                quality=analysis.get("data_quality") or assess_data_quality(analysis)
                snapshots=store.snapshots_for_fixture(int(row["fixture_id"]))
                drift=compare_drift(snapshots)
                dynamic=dynamic_confidence(float(row.get("confidence") or 50),data_quality=quality["score"],agreement=float(internal.get("model_agreement") or 50),odds_available=bool(row.get("odds")),lineups_available=bool(internal.get("context",{}).get("lineups_available")),drift_points=drift.get("max_drift",0))
                audit=analysis.get("prediction_audit") or build_audit({**analysis,"best_pick":{"label":row.get("pick"),"key":row.get("market_key"),"probability_pct":round(float(row.get("probability") or 0)*100,1)}},quality,dynamic,monte)
            except Exception as exc: error=f"Audit payload tidak dapat dibaca: {exc}"
    return templates.TemplateResponse(request=request,name="intelligence.html",context=ctx(request,prediction_id=prediction_id,row=row,audit=audit,monte=monte,dynamic=dynamic,drift=drift,error=error))

@app.get("/reliability", response_class=HTMLResponse)
async def reliability_page(request: Request):
    if not auth(request): return login_redirect()
    return templates.TemplateResponse(request=request,name="reliability.html",context=ctx(request,reliability=reliability_summary(store.recent_predictions(10000))))

@app.get("/data-quality", response_class=HTMLResponse)
async def data_quality_page(request: Request):
    if not auth(request): return login_redirect()
    records = store.decision_records_for_date(today_wita_iso(), 60)
    rows=[]
    for row in records:
        analysis = row.get("analysis") or {}
        quality = analysis.get("data_quality") or assess_data_quality(analysis)
        rows.append({
            **row,
            "quality": quality,
            "decision_label": row.get("final_label") or "NO BET",
            "decision_tier": row.get("final_tier") or "NO_BET",
            "selected_pick_label": row.get("recommendation_label") if row.get("published") else None,
            "risk_level": row.get("risk_level") or "-",
        })
    return templates.TemplateResponse(request=request,name="data_quality.html",context=ctx(request,rows=rows))


@app.get("/automation", response_class=HTMLResponse)
async def automation_page(request: Request, message: str | None = None):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.RUN_AUTOMATION)
    snapshot = settlement_queue.build()
    summary = snapshot.summary()
    return templates.TemplateResponse(request=request, name="automation.html", context=ctx(
        request, status=summary, queue_snapshot=snapshot,
        investigation_rows=store.settlement_investigation_rows(100),
        void_audit=store.settlement_void_audit(),
        runs=store.automation_runs(),
        engine_running=automation_engine.running, interval_minutes=settings.settlement_interval_minutes,
        message=message,
    ))


@app.post("/automation/run")
async def automation_run(request: Request):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.RUN_SETTLEMENT)
    result = await automation_engine.run_once(trigger="MANUAL")
    message = (
        f"Settlement selesai: {result.get('settled', 0)} prediksi diperbarui "
        f"({result.get('wins', 0)} WIN, {result.get('losses', 0)} LOSS, {result.get('voids', 0)} VOID)."
        if result.get("status") != "SKIPPED" else result.get("message", "Settlement dilewati.")
    )
    from urllib.parse import quote
    return RedirectResponse(f"/automation?message={quote(message)}", status_code=303)


@app.post("/automation/requeue-investigation")
async def automation_requeue_investigation(request: Request):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.RUN_SETTLEMENT)
    updated = store.requeue_investigation()
    message = f"{updated} fixture investigasi dikembalikan ke antrean recovery."
    return RedirectResponse(f"/automation?message={quote(message)}", status_code=303)


@app.post("/automation/run-overdue")
async def automation_run_overdue(request: Request):
    if not auth(request): return login_redirect()
    require_permission(request, Permission.RUN_SETTLEMENT)
    result = await automation_engine.run_once(trigger="MANUAL_OVERDUE", overdue_only=True)
    message = (
        f"Recovery overdue selesai: {result.get('checked_fixtures', 0)} fixture diperiksa, "
        f"{result.get('settled', 0)} prediksi diperbarui "
        f"({result.get('wins', 0)} WIN, {result.get('losses', 0)} LOSS, {result.get('voids', 0)} VOID)."
        if result.get("status") != "SKIPPED" else result.get("message", "Recovery dilewati.")
    )
    return RedirectResponse(f"/automation?message={quote(message)}", status_code=303)

