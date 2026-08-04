from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.ai.failover import has_active_provider
from app.auth.csrf import verify_csrf
from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.learning import practice as practice_service
from app.learning import streaks as streaks_service
from app.learning.progress import MIN_SCORED_VERSIONS_FOR_TREND, has_scored_history, recurring_mistakes, score_trend
from app.learning.timezone_utils import DEFAULT_TIMEZONE
from app.rate_limit import AI_PRACTICE_GENERATION_RATE_LIMIT, get_user_or_ip, limiter

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _goal_timezone(goal) -> str:
    return goal.timezone if goal else DEFAULT_TIMEZONE


@router.get("/progress")
def progress_dashboard(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    goal = streaks_service.get_goal(db, user.id)
    timezone_name = _goal_timezone(goal)
    scored_count = has_scored_history(db, user.id)

    return templates.TemplateResponse(
        request,
        "progress.html",
        {
            "scored_count": scored_count,
            "has_enough_history": scored_count >= MIN_SCORED_VERSIONS_FOR_TREND,
            "trend": score_trend(db, user.id, timezone_name) if scored_count >= MIN_SCORED_VERSIONS_FOR_TREND else [],
            "mistakes": recurring_mistakes(db, user.id),
            "timezone_name": timezone_name,
        },
    )


@router.get("/goals")
def goals_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    goal = streaks_service.get_goal(db, user.id)
    timezone_name = _goal_timezone(goal)
    return templates.TemplateResponse(
        request,
        "goals.html",
        {
            "goal": goal,
            "streak": streaks_service.current_streak(db, user.id, timezone_name),
            "week": streaks_service.week_progress(db, user.id, timezone_name),
            "timezone_name": timezone_name,
            "form_error": None,
        },
    )


@router.post("/goals")
def save_goal(
    request: Request,
    target_submissions: int = Form(...),
    timezone_name: str = Form(...),
    enabled: bool = Form(False),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    try:
        goal = streaks_service.set_goal(db, user.id, target_submissions, timezone_name.strip(), enabled)
    except streaks_service.GoalValidationError as exc:
        existing_goal = streaks_service.get_goal(db, user.id)
        fallback_timezone = _goal_timezone(existing_goal)
        return templates.TemplateResponse(
            request,
            "goals.html",
            {
                "goal": existing_goal,
                "streak": streaks_service.current_streak(db, user.id, fallback_timezone),
                "week": streaks_service.week_progress(db, user.id, fallback_timezone),
                "timezone_name": timezone_name.strip() or fallback_timezone,
                "form_error": str(exc),
            },
            status_code=400,
        )
    return RedirectResponse("/goals", status_code=303)


@router.get("/practice")
def practice_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    exercises = practice_service.list_exercises(db, user.id)
    has_ai_provider = has_active_provider(db, user.id)
    return templates.TemplateResponse(
        request,
        "practice.html",
        {"exercises": exercises, "has_ai_provider": has_ai_provider, "generation_error": None},
    )


@router.post("/practice/generate")
def generate_local_practice(
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    practice_service.generate_local_exercises(db, user.id)
    return RedirectResponse("/practice", status_code=303)


@router.post("/practice/generate-ai")
@limiter.limit(AI_PRACTICE_GENERATION_RATE_LIMIT, key_func=get_user_or_ip)
def generate_ai_practice(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    has_ai_provider = has_active_provider(db, user.id)
    _rows, error = practice_service.generate_ai_exercises(db, user.id)
    exercises = practice_service.list_exercises(db, user.id)
    return templates.TemplateResponse(
        request,
        "practice.html",
        {"exercises": exercises, "has_ai_provider": has_ai_provider, "generation_error": error},
        status_code=400 if error else 200,
    )


@router.post("/practice/{exercise_id}/complete")
def complete_practice(
    exercise_id: int,
    response: str = Form(""),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    practice_service.submit_completion(db, user.id, exercise_id, response)
    return RedirectResponse("/practice", status_code=303)
