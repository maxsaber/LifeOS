# Apple Photos Face Recognition Data Review

Generated: 2026-02-02

---

## Summary Statistics

- **Total named people**: 31 (with at least 1 photo)
- **People linked to Apple Contacts**: 24
- **People NOT linked to Contacts**: 7 (Malea, Taylor, Burger, Audrey, Fiona, Dan Esty, Aaviya)
- **Total photos with 2+ named people**: 2,523 (relationship discovery candidates)

---

## All Named People (sorted by photo count)

| Name | Display Name | Photos | Linked to Contacts |
|------|--------------|--------|-------------------|
| Malea | Malea | 3,286 | No |
| Nathan Ramia | Nathan | 2,305 | Yes |
| Taylor | Taylor | 883 | No |
| Anne Christianson | Anne | 842 | Yes |
| Thy | Thy | 402 | Yes |
| Sarah Esty | Sarah | 184 | Yes |
| Alix Haber | Alix | 160 | Yes |
| Patricia Ramia | Patricia | 140 | Yes |
| Sam Goodgame | Sam | 133 | Yes |
| Emily Durfee | Emily | 133 | Yes |
| Maria Stosz | Maria | 132 | Yes |
| Heather Williams | Heather | 122 | Yes |
| Sabrina Roshan | Sabrina | 112 | Yes |
| Bill Ramia | Bill | 109 | Yes |
| Burger | Burger | 106 | No |
| Audrey Van Drimmelen | Audrey Van Drimmelen | 87 | No |
| Ben Warren | Ben | 83 | Yes |
| Fiona Gibson | Fiona Gibson | 65 | No |
| Michael Frossard | Michael | 52 | Yes |
| Dan Esty | Dan Esty | 46 | No |
| O'Mara | O'Mara | 32 | Yes |
| Aaviya Sribinder | Aaviya Sribinder | 31 | No |
| Evan Marcantonio | Evan | 30 | Yes |
| Bryan Han | Bryan | 25 | Yes |
| Cissy | Cissy | 24 | Yes |
| Elizabeth Weiland | Elizabeth | 19 | Yes |
| Lucy Jones | Lucy | 19 | Yes |
| Swetha | Swetha | 18 | Yes |
| Ben Calvin | Ben | 15 | Yes |
| Matthew Stafford | Matthew | 13 | Yes |
| Neal Desai | Neal | 13 | Yes |
| Russell Pildes | Russell | 3 | Yes |

**Total: 31 people with 9,360 face detections**

---

## Sample Multi-Person Photos (recent, 2+ people)

| Date | People in Photo | Count |
|------|-----------------|-------|
| 2026-01-25 20:01:17 | Taylor, Nathan Ramia, Malea | 3 |
| 2026-01-25 20:01:14 | Taylor, Nathan Ramia, Malea | 3 |
| 2026-01-25 20:01:13 | Taylor, Nathan Ramia, Malea | 3 |
| 2026-01-25 20:01:00 | Taylor, Nathan Ramia, Malea | 3 |
| 2026-01-25 20:00:59 | Taylor, Nathan Ramia, Malea | 3 |
| 2026-01-25 20:00:56 | Taylor, Nathan Ramia, Malea | 3 |
| 2026-01-25 20:00:48 | Nathan Ramia, Malea | 2 |
| 2026-01-04 22:41:48 | Taylor, Nathan Ramia | 2 |
| 2026-01-04 22:41:21 | Bill Ramia, Patricia Ramia, Taylor, Nathan Ramia | 4 |
| 2026-01-04 22:15:37 | Bill Ramia, Patricia Ramia, Nathan Ramia | 3 |
| 2026-01-04 22:01:10 | Audrey Van Drimmelen, Taylor | 2 |
| 2025-12-31 03:52:22 | Taylor, Nathan Ramia | 2 |
| 2025-12-29 23:09:11 | Audrey Van Drimmelen, Taylor, Nathan Ramia | 3 |
| 2025-12-28 19:25:23 | Bill Ramia, Patricia Ramia, Taylor, Nathan Ramia | 4 |
| 2025-12-27 19:57:36 | Bill Ramia, Patricia Ramia, Taylor, Nathan Ramia | 4 |
| 2025-12-26 01:54:15 | Taylor, Malea | 2 |
| 2025-12-25 21:59:18 | Burger, Malea | 2 |

---

## Relationship Signals from Photos

These co-appearances would create/strengthen relationships:

| Person A | Person B | Expected Signal |
|----------|----------|-----------------|
| Nathan Ramia | Taylor | High (hundreds of photos together) |
| Nathan Ramia | Malea | High (hundreds of photos together) |
| Taylor | Malea | High (family photos) |
| Nathan Ramia | Bill Ramia | Medium (family gatherings) |
| Nathan Ramia | Patricia Ramia | Medium (family gatherings) |
| Taylor | Audrey Van Drimmelen | Medium (friend photos) |
| Malea | Burger | Medium (pet photos) |

---

## Notes

1. **"Burger" is likely a pet** (106 photos, appears with Malea)
2. **Duplicates exist** with 0 photos (Taylor, Malea appear multiple times with Z_PK but ZFACECOUNT=0)
3. **Display names are often first-name only** (Nathan, Anne, etc.)
4. **Date range**: Photos span from ~2020 to 2026-01-25

---

## Questions Before Implementation

1. Should "Burger" (pet) be excluded or included?
2. Are there any people here you DON'T want synced to LifeOS?
3. The 7 unlinked people (Malea, Taylor, etc.) - should I match by exact name?
