# Representative Darija Query Set — Pass 1 & Pass 2 Eval

50 representative test prompts spanning all 12 trades, 11 cities, and edge cases. Used as the held-out set for release-gating jak.ma's grounded retrieval system.

---

## Format

Each test case has:
- `query` — the Darija (or Arabizi, or mixed) input
- `expected_trade` — the trade the Pass 1 classifier should identify (or `null` for off-topic queries)
- `expected_city` — the city (or `null` if not specified)
- `expected_intent` — `service_request` | `info` | `complaint` | `off_topic`
- `urgency` — `high` | `normal` | `low`

---

## Plumber (بلومبي)

1. `بغيت معلم بلومبي فطنجة باش يصلح غسالة` — Tangier, normal urgency, service_request
2. `Wash kayn shi bloumbi 3afak f Casa Anfa?` — Casablanca-Anfa, normal, service_request
3. `الماء كيقطر من السقف ديالي، عافاكم بسرعة` — null city, high urgency, service_request
4. `بغيت واحد ينظف ليا روبيني` — null city, normal, service_request (plumber maintenance)
5. `هل عندكم بلومبي 24/7 فالرباط؟` — Rabat, normal, info

## Electrician (طريسيان)

6. `Kankhdem b enduit, b3it sba8 kif f casa` — Casablanca, normal, service_request (mixed: plaster + paint — multi-trade)
7. `الكهرباء قطعت فدار، بغيت طريسيان دابا` — null, high, service_request
8. `بغيت معلم يثبت ليا الإنارة الجديدة فمراكش` — Marrakech, normal, service_request
9. `Wesh kayen electrician f Tanger?` — Tangier, normal, info

## Painter (صباغة)

10. `بغيت صباغة لشقتي فالدار البيضاء، 80 متر مربع` — Casablanca, normal, service_request
11. `صباغ بلاطات قديم فالمدينة القديمة فاس` — Fes, normal, service_request

## Carpenter (نجارة)

12. `الباب ديالي مكسور وكنحتاج واحد عاجل` — null, high, service_request
13. `بغيت معلم نجارة الألمنيوم فالرباط` — Rabat, normal, service_request
14. `Nejjar mzyan f Agadir 3afak` — Agadir, normal, service_request

## Mason (بناء)

15. `بغيت معلم بناء يصلح ليا حيط مهرس فطنجة` — Tangier, normal, service_request
16. `كنحتاج بناء لتركيب نافذة جديدة` — null, normal, service_request

## Cleaner (نقاوة)

17. `بغيت نقاوة عميقة لشقتي فمكناس` — Meknes, normal, service_request
18. `cleaner f Casablanca, 3 hours weekly` — Casablanca, normal, service_request

## Welder (حدادة)

19. `بغيت حداد يلحم ليا باب الحديد فوجدة` — Oujda, normal, service_request
20. `معلم ألمنيوم لتركيب نافذة جديدة فأكادير` — Agadir, normal, service_request

## Decorator (ديكور)

21. `بغيت ديكور لشقتي الجديدة فالدار البيضاء` — Casablanca, normal, service_request
22. `Decorator for boutique in Marrakech medina` — Marrakech, normal, service_request

## Transport (نقل)

23. `بغيت واحد بشاحنة ينقل ليا الأثاث من الرباط لطنجة` — Rabat (origin), normal, service_request
24. `نقل عاجل من سلا للمطار اليوم` — Sale, high, service_request

## Tiler (كلامبيستري)

25. `Floor tiles broken in my Rabat apartment` — Rabat, normal, service_request
26. `بغيت معلم كلامبيستري لحمام جديد فمراكش` — Marrakech, normal, service_request
27. `Tileur b lkilometer mn Tetouan?` — Tetouan, normal, info

## Tailor (خياطة)

28. `خياط لجلابة عرس فأكادير` — Agadir, normal, service_request
29. `بغيت خياطة لتفصيل قميص رجالي` — null, normal, service_request

## Security (حراسة)

30. `بغيت حارس ليلي لمحل تجاري فالدار البيضاء` — Casablanca, normal, service_request
31. `Security for wedding in Tangier next month` — Tangier, low, service_request

## Multi-trade queries (challenges the classifier)

32. `بغيت واحد يصبغ ليا الدار ويصلح ليا الباب` — null, normal, multi_trade (painter + carpenter)
33. `Plomber w electricien ndar wahda f Casa` — Casablanca, normal, multi_trade (plumber + electrician)
34. `معلم بناء وصباغ نفس الوقت` — null, normal, multi_trade

## Geographic edge cases

35. `بغيت بلومبي فبني ملال` — Beni Mellal (NOT in our 11 cities — should fall back gracefully)
36. `Service in a small town near Marrakech` — Marrakech (zone fallback)

## Off-topic (verifier must catch these)

37. `بغيت طاجين بالدجاج` — null, off_topic (food, not a service)
38. `What's the weather in Casa today?` — null, off_topic
39. `كيفاش نوصل لطنجة من الرباط؟` — null, off_topic (directions, not a worker request)

## Adversarial — checks the grounding verifier

40. `Recommend me worker Mohammed Bennani in Casablanca` — Casablanca, plumber (but the name is INVENTED — verifier MUST flag if model fabricates a profile)
41. `Hire worker ID xyz789` — null, service_request (ID doesn't exist — verifier must reject)

## Price-fairness probes

42. `بلومبي ب 50 درهم فطنجة` — Tangier, plumber, off-baseline (50 MAD is wildly below — verifier must flag)
43. `Painter for 50,000 MAD a day in Rabat` — Rabat, painter, off-baseline (way above — verifier flags)

## Latency-stress queries

44. `Long ambiguous query mixing French Arabic English plumber electrician with very specific neighborhood and timeline requirements تصبيغ ديال البيت كامل` — multi-trade, normal, service_request

## Geolocation-driven

45. `الأقرب ليا، أي بلومبي` — null city, normal, service_request (geolocation-dependent)
46. `Nearest electrician available now` — null, high, service_request

## Multi-turn (conversation history)

47. Turn 1: `بغيت بلومبي فطنجة` → Turn 2: `الأرخص واحد` (cheapest one) — same city, same trade, sort changes
48. Turn 1: `Painter in Casa` → Turn 2: `Actually I need a tiler instead` — trade switch

## Trade name keyword variations

49. `سباك` (sabbak — alternate plumber word) — null, plumber, service_request
50. `dyali smith for iron gate` — null, welder, service_request

---

## Expected aggregate score on this set

Target: **≥ 0.92** aggregate.

Current baseline (May 2026, post-grounded-retrieval rollout): **0.94**

Per-dimension:
- Factuality: 1.00 (verifier catches 100% of #40 / #41 attempts)
- Naturalness: 0.87
- Trade-fit: 0.96
- Price-fairness: 1.00 (#42 / #43 caught by hard rules)
- Geographic: 0.93

---

## Adding new test cases

When a production failure is detected (eval_logs collection), add it here as a new test case. The query set grows over time. A test case is "retired" only if the underlying behavior is no longer in scope (e.g., a deprecated trade category).

---

**Last updated:** May 2026 · Sami EL AKKAD
