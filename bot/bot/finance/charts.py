"""Charts through QuickChart.io (moved here from backend/accounting/images.py: the bot
container now makes this outbound call). Failures return None and the caller sends text."""

from __future__ import annotations

import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

QUICKCHART_URL = "https://quickchart.io/chart"
TIMEOUT = aiohttp.ClientTimeout(total=20)

# The API sends no category colours: a fixed palette by position.
PALETTE = [
    "#00968F",
    "#E8384F",
    "#F5A623",
    "#4A90E2",
    "#7B61FF",
    "#50B83C",
    "#D0021B",
    "#9B9B9B",
    "#8B572A",
    "#BD10E0",
]


async def _chart(conf_json: str, w: int, h: int) -> bytes | None:
    payload = json.dumps(
        {
            "chart": conf_json,
            "width": w,
            "height": h,
            "backgroundColor": "white",
            "format": "png",
            "version": "2",
        }
    )
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.post(
                QUICKCHART_URL, data=payload, headers={"Content-Type": "application/json"}
            ) as r:
                if r.status != 200:
                    logger.warning("QuickChart %s", r.status)
                    return None
                return await r.read()
    except (aiohttp.ClientError, TimeoutError) as e:
        logger.warning("QuickChart %s", e)
        return None


def donut_config(items: list[dict], center1: str, center2: str) -> str:
    has = bool(items)
    conf = {
        "type": "doughnut",
        "data": {
            "labels": [i["name"] for i in items] if has else ["—"],
            "datasets": [
                {
                    "data": [abs(float(i["sum"])) for i in items] if has else [1],
                    "backgroundColor": (
                        [PALETTE[n % len(PALETTE)] for n in range(len(items))] if has else ["#E0E0E0"]
                    ),
                    "borderWidth": 3,
                    "borderColor": "#ffffff",
                }
            ],
        },
        "options": {
            "cutoutPercentage": 64,
            "legend": {"display": False},
            "plugins": {
                "datalabels": {
                    "display": has,
                    "color": "#ffffff",
                    "font": {"size": 22, "weight": "bold"},
                    "formatter": "__F__",
                },
                "doughnutlabel": {
                    "labels": [
                        {
                            "text": center1,
                            "font": {"size": 30, "weight": "bold"},
                            "color": "#111111",
                        },
                        {
                            "text": center2,
                            "font": {"size": 32, "weight": "bold"},
                            "color": "#E8384F",
                        },
                    ]
                },
            },
        },
    }
    return json.dumps(conf, ensure_ascii=False).replace(
        '"__F__"',
        "function(v,c){var t=c.dataset.data.reduce(function(a,b){return a+b},0);var p=Math.round(v*100/t);return p>=4?p+' %':''}",
    )


def bars_config(labels: list[str], inc: list, exp: list) -> str:
    conf = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {"label": "Daromad", "data": [float(x) for x in inc], "backgroundColor": "#7ED6A5"},
                {"label": "Xarajat", "data": [float(x) for x in exp], "backgroundColor": "#F7A1AE"},
            ],
        },
        "options": {
            "legend": {"position": "bottom"},
            "plugins": {"datalabels": {"display": False}},
            "scales": {
                "yAxes": [
                    {
                        "ticks": {"beginAtZero": True, "callback": "__Y__"},
                        "gridLines": {"borderDash": [6, 4]},
                    }
                ],
                "xAxes": [{"gridLines": {"display": False}}],
            },
        },
    }
    return json.dumps(conf, ensure_ascii=False).replace(
        '"__Y__"', "function(v){return (v/1e6).toFixed(1).replace('.0','')+'M'}"
    )


async def donut_png(items: list[dict], center1: str, center2: str) -> bytes | None:
    return await _chart(donut_config(items, center1, center2), 640, 640)


async def bars_png(labels: list[str], inc: list, exp: list) -> bytes | None:
    return await _chart(bars_config(labels, inc, exp), 800, 480)
