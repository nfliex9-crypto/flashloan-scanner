from aegis.intelligence import aggregate_finra_rows, score_sec_activity


def test_finra_aggregates_reporting_facilities_and_scores_anomaly():
    rows = []
    for day, short in [
        ("2026-10-01", 400),
        ("2026-10-02", 410),
        ("2026-10-03", 420),
        ("2026-10-04", 430),
        ("2026-10-05", 800),
    ]:
        rows.extend(
            [
                {
                    "tradeReportDate": day,
                    "totalParQuantity": 500,
                    "shortParQuantity": short / 2,
                    "shortExemptParQuantity": 5,
                },
                {
                    "tradeReportDate": day,
                    "totalParQuantity": 500,
                    "shortParQuantity": short / 2,
                    "shortExemptParQuantity": 5,
                },
            ]
        )

    out = aggregate_finra_rows(rows)

    assert out["latest"]["date"] == "2026-10-05"
    assert out["latest"]["total_volume"] == 1000
    assert out["latest"]["short_volume"] == 800
    assert out["latest"]["short_volume_ratio"] == 0.8
    assert out["anomaly_score"] > 15


def test_sec_score_is_attention_only_not_direction():
    rows = [
        {"form": "4", "filingDate": "2026-10-06", "accessionNumber": "a", "primaryDocument": "x"},
        {"form": "8-K", "filingDate": "2026-10-05", "accessionNumber": "b", "primaryDocument": "y"},
        {"form": "10-Q", "filingDate": "2026-09-20", "accessionNumber": "c", "primaryDocument": "z"},
    ]

    out = score_sec_activity(rows)

    assert out["attention_score"] > 18
    assert out["direction"] == "UNKNOWN"
    assert out["role"] == "CONTEXT_ONLY"
