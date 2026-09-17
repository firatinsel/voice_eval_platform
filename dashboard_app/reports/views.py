from django.shortcuts import render
from django.db.models import Avg, Count, Q
from .models import EvaluationRecord

def quality_report_view(request):
    bot_filter = request.GET.get("bot_id", "")
    provider_filter = request.GET.get("provider", "")
    
    queryset = EvaluationRecord.objects.all()
    if bot_filter:
        queryset = queryset.filter(bot_id=bot_filter)
    if provider_filter:
        queryset = queryset.filter(Q(stt_provider=provider_filter) | Q(tts_provider=provider_filter))

    total = queryset.count()
    if total == 0:
        return render(request, "reports/dashboard.html", {"empty": True})

    avg_score = queryset.aggregate(avg=Avg("overall_score"))["avg"] or 0.0
    retry_count = queryset.filter(action__in=["retry_stt", "retry_tts"]).count()
    failure_count = queryset.filter(action__in=["safe_fallback", "switch_provider", "ask_repeat"]).count()

    actions = queryset.values("action").annotate(count=Count("id")).order_by("-count")
    for a in actions:
        a["pct"] = (a["count"] / total) * 100

    stt_lats = queryset.exclude(stt_provider__isnull=True).values("stt_provider").annotate(avg=Avg("stt_latency_ms"), count=Count("id"))
    tts_lats = queryset.exclude(tts_provider__isnull=True).values("tts_provider").annotate(avg=Avg("tts_latency_ms"), count=Count("id"))

    context = {
        "total": total,
        "avg_score": round(avg_score, 3),
        "retry_rate": round((retry_count / total) * 100, 2),
        "failure_rate": round((failure_count / total) * 100, 2),
        "actions": actions,
        "stt_lats": stt_lats,
        "tts_lats": tts_lats,
        "bots": EvaluationRecord.objects.values_list("bot_id", flat=True).distinct(),
        "selected_bot": bot_filter,
    }
    return render(request, "reports/dashboard.html", context)