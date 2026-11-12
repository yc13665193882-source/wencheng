# skills.sh discovery verification

## Search verified on 2026-11-12

At **14:29 UTC (22:29 China Standard Time)**, both full-site searches returned Wencheng. The English query `wencheng` returned it as the only result. The Chinese query `文澄` included it at position 98 in the 100 returned results, so `wencheng` is currently the more direct discovery query. Both entries identified `yc13665193882-source/wencheng/wencheng` and showed one recorded install.

The official `skills@1.7.6 find wencheng` and `skills@1.7.6 find 文澄` commands also returned the correct installation source. These checks were read-only, with CLI telemetry disabled. The detail page rendered the actual skill content and showed `Installs 1` and `First Seen 2 days ago`.

**English and Chinese search acceptance now passes.** The exact time of propagation is unknown; it occurred between the November 10 and November 12 checks. The one recorded install does not establish an external user, since the publisher's real local installation was already recorded during the earlier investigation. The prepared upstream issue was not submitted before the previous session was interrupted; no issue was filed after search recovered.

## Initial registration check on 2026-11-10

Checked on **2026-11-10 at 13:40 UTC (21:40 China Standard Time)**.

**The skill detail page and downloadable snapshot are available. English and Chinese search did not yet return Wencheng. Direct installation works independently of search.**

中文摘要：已修复发布流程中未触发收录的问题，补充“文澄”品牌描述，完成一次真实使用安装并确认官方安装事件返回成功。详情页和 5 个技能文件快照已可用；截至上述时间，全站搜索 `wencheng` 和 `文澄` 仍未返回本项目，不能宣称搜索验收已通过。

## What was missing

The earlier [installation acceptance](INSTALLATION-VALIDATION.md) deliberately set `DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1`. Those runs verified installation and document workflows, but did not trigger directory registration. The [official FAQ](https://www.skills.sh/docs/faq) describes automatic listing through anonymous CLI installation telemetry.

The existing `skills/wencheng/SKILL.md` layout is supported by the [official discovery rules](https://github.com/vercel-labs/skills/blob/main/docs/creating-skills.md). Its frontmatter is valid and does not mark the skill internal. No duplicate root skill or custom discovery manifest is needed.

[Commit c315826](https://github.com/yc13665193882-source/wencheng/commit/c315826fe0e252760866ff16e4cde2bd332249a4) added `文澄` to the description while retaining the stable installation name `wencheng`. The [catalog API documentation](https://www.skills.sh/docs/api) describes searching by name or description; the metadata change supplies the Chinese brand without guaranteeing search propagation.

## Real installation and observed results

The official npm `skills@1.7.6` package was used for one actual global Codex installation on Windows, with telemetry enabled. The installed copy was bound to the existing Wencheng application. All five skill text files matched the published source after normalizing line endings, the launcher matched byte-for-byte, and `projects` succeeded from an unrelated directory without application-path environment overrides.

| Check | Observed result |
| --- | --- |
| GitHub public-repository check | HTTP 200 at 13:34:59 UTC; repository confirmed public |
| Official CLI install event | HTTP 200 at 13:35:03 UTC; `source=yc13665193882-source/wencheng`, `skills=wencheng`, `agents=codex`, `global=1` |
| Skill path in the event | `{"wencheng":"skills/wencheng/SKILL.md"}` |
| [Skill detail page](https://www.skills.sh/yc13665193882-source/wencheng/wencheng) | Actual rendered `文澄 · Wencheng` content present by 13:36 UTC; still present at 13:40 UTC |
| [Download snapshot](https://www.skills.sh/api/download/yc13665193882-source/wencheng/wencheng) | HTTP 200; SKILL.md, launcher, two references and agent metadata present |
| Full-site search: `wencheng` | HTTP 200; no matching Wencheng entry among six returned results |
| Full-site search: `文澄` | HTTP 200; no matching Wencheng entry among the 100 returned results |
| Owner-filtered searches | Both queries returned HTTP 200 with zero entries at 13:36 UTC |
| Official `skills find` | Both queries still omitted Wencheng |

The installation request was observed without changing its data, response or destination. No synthetic installation events or repeated installations were used. Automated smoke tests keep telemetry disabled.

The detail page still showed `Installs –` and `First Seen –`. Successful event delivery and a readable skill snapshot do not prove that installation counts or the search index have updated. The official tracker contains a [similar unresolved report](https://github.com/vercel-labs/skills/issues/2340); it is evidence of the same symptom, not proof of the exact server-side cause here. There is no published search-refresh deadline in the referenced documentation.

The [Snyk audit](https://www.skills.sh/yc13665193882-source/wencheng/wencheng/security/snyk) reports W012 / medium for downloading and running a runtime from an individual publisher. It recognizes the pinned SHA256 check. The official `find-skills` entry has the [same warning level](https://www.skills.sh/vercel-labs/skills/find-skills/security/snyk) and remains searchable, so a warning alone does not establish a search block.

## Install and recheck

Use the commands in the [Chinese README](../../README.md#通过-skillssh-安装) or [English README](../../README.en.md#install-through-skillssh). They install from the public repository and then set up the pinned runtime; directory search is not a prerequisite.

From a source checkout, check current directory state without installing anything:

```sh
node scripts/check_skills_directory.mjs --output test-output/skills-directory.json
```

The script makes three GET requests: full-site English search, full-site Chinese search and the detail page. It matches both repository and skill ID, checks rendered skill content rather than HTTP 200 alone, and reports transport or schema errors separately from a valid search with no match. Output is a point-in-time observation, not a permanent listing guarantee. Exit code zero means the check ran successfully; inspect `state` for search availability.

For future publication checks, separate installation acceptance, actual installation-event delivery, detail-page content and search results. Keep automated tests opted out. If a legitimate installation has sent its event successfully but search remains absent, preserve the timestamps and response evidence for the platform maintainers instead of repeatedly installing.
