"""Discover official Sichuan University channels from the university directory.

The script never logs in. It refreshes an inventory of public departments,
schools, service units, and student-facing systems. Failed refreshes preserve
the previous catalog.
"""
from __future__ import annotations

import json
import re
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from lxml import html


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "scu-channel-catalog.json"
JS_OUTPUT = ROOT / "scu-channels.js"
TZ = timezone(timedelta(hours=8))
UA = "SCUStudyRadar/0.2 (public channel directory)"
DIRECTORIES = {
    "机关部处": "https://www.scu.edu.cn/zzjg1/jgbc.htm",
    "院系": "https://www.scu.edu.cn/zzjg1/yx.htm",
    "业务单位": "https://www.scu.edu.cn/zzjg1/ywdw.htm",
}
KEYWORDS = re.compile(r"学院|学系|系$|处$|部$|委员会|办公室|中心|研究院|研究所|图书馆|档案馆|出版社|医院|实验室|平台|基地|工会|党校|基金会|校友")
SKIP = {"学生", "教职工", "校友", "访客", "首页", "组织机构", "机关部处", "院系", "业务单位", "纪检监察机构", "学校概况"}
PUBLIC_SERVICES = [
    {"name":"云上川大服务大厅","url":"https://my.scu.edu.cn/portal/home","kind":"登录服务","access":"login"},
    {"name":"本科教务系统（个人课表/选课/成绩）","url":"http://zhjw.scu.edu.cn/index","kind":"课程教务","access":"login"},
    {"name":"本学期开课信息查询","url":"https://zhjwjs.scu.edu.cn/teacher/personalSenate/giveLessonInfo/thisSemesterClassSchedule/indexPublic","kind":"课程教务","access":"public-or-login"},
    {"name":"空闲教室查询","url":"https://cir.scu.edu.cn/cir/index.html","kind":"课程教务","access":"public-or-login"},
    {"name":"四川大学教务处","url":"https://jwc.scu.edu.cn/","kind":"课程教务","access":"public"},
    {"name":"川大校历","url":"https://jwc.scu.edu.cn/cdxl.htm","kind":"课程教务","access":"public"},
    {"name":"本科教学作息时间","url":"https://jwc.scu.edu.cn/info/1065/8056.htm","kind":"课程教务","access":"public"},
    {"name":"课程资源·大川学堂","url":"https://ecourse.scu.edu.cn/","kind":"学习平台","access":"public-or-login"},
    {"name":"学习通","url":"https://fanya.scu.edu.cn/","kind":"学习平台","access":"login"},
    {"name":"爱课堂","url":"https://iclass.scu.edu.cn/","kind":"学习平台","access":"login"},
    {"name":"四川大学图书馆","url":"https://lib.scu.edu.cn/","kind":"学习资源","access":"public-or-login"},
    {"name":"四川大学就业信息网","url":"https://jy.scu.edu.cn/","kind":"就业发展","access":"public"},
    {"name":"四川大学研究生院","url":"https://gs.scu.edu.cn/","kind":"研究生教育","access":"public"},
    {"name":"四川大学研究生招生","url":"https://yz.scu.edu.cn/","kind":"招生","access":"public"},
    {"name":"四川大学本科招生","url":"https://zs.scu.edu.cn/","kind":"招生","access":"public"},
    {"name":"学生工作部","url":"https://xgb.scu.edu.cn/","kind":"学生事务","access":"public"},
    {"name":"校团委","url":"https://tuanwei.scu.edu.cn/","kind":"学生事务","access":"blocked-check"},
    {"name":"校园活动","url":"https://www.scu.edu.cn/index/xw/xyhd.htm","kind":"学生事务","access":"public"},
    {"name":"国际合作与交流处","url":"https://global.scu.edu.cn/","kind":"国际交流","access":"public"},
    {"name":"社会科学研究处","url":"https://ssd.scu.edu.cn/","kind":"科研","access":"public"},
    {"name":"科学技术发展研究院","url":"https://kyy.scu.edu.cn/","kind":"科研","access":"public"},
    {"name":"四川大学信息公开","url":"https://xxgk.scu.edu.cn/","kind":"信息公开","access":"public"},
    {"name":"校园地图","url":"https://gis.scu.edu.cn/","kind":"校园生活","access":"public"},
    {"name":"信息化建设与管理办公室","url":"https://info.scu.edu.cn/","kind":"校园服务","access":"public"},
    {"name":"四川大学校友总会","url":"https://scuaa.scu.edu.cn/","kind":"校友","access":"public"},
]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read(3_000_000)


def normalize_name(value: str) -> str:
    # Parentheses are meaningful in official names such as “法学院（律师学院）”.
    return re.sub(r"\s+", "", value).strip("-—· ")


def discover(group: str, url: str) -> list[dict]:
    tree = html.fromstring(fetch(url), base_url=url)
    found = {}
    for anchor in tree.xpath("//a[@href]"):
        name = normalize_name(anchor.get("title") or anchor.text_content())
        target = urljoin(url, anchor.get("href")).split("#")[0]
        host = urlsplit(target).hostname or ""
        if name in SKIP or not KEYWORDS.search(name):
            continue
        if not target.startswith(("http://", "https://")):
            continue
        if not (host.endswith("scu.edu.cn") or host in {"www.wchscu.cn", "www.motherchildren.com", "www.hxkq.org", "www.wcfh.com.cn"}):
            continue
        key = host.lower()
        found.setdefault(key, {"name": name[:100], "url": target, "kind": group, "access": "public-or-login"})
    return list(found.values())


def atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    previous = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    groups, errors = {}, []
    for group, url in DIRECTORIES.items():
        try:
            groups[group] = discover(group, url)
        except Exception as exc:
            errors.append({"group": group, "url": url, "error": str(exc)})
            groups[group] = previous.get("groups", {}).get(group, [])
    groups["公共服务"] = PUBLIC_SERVICES
    total = sum(len(rows) for rows in groups.values())
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(TZ).isoformat(),
        "officialDirectory": "https://www.scu.edu.cn/zzjg1/yx.htm",
        "total": total,
        "groups": groups,
        "errors": errors,
        "note": "目录不等于全部已接入抓取；access 标记说明公开、登录或校验边界。",
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    atomic_write(OUTPUT, serialized + "\n")
    atomic_write(JS_OUTPUT, "window.SCU_CHANNEL_CATALOG=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(json.dumps({"channels": total, "errors": len(errors), "output": str(OUTPUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
