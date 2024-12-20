import argparse
import os
import pickle
import re
import sys
from enum import Enum
import time
from bs4 import BeautifulSoup as BS
from typing import List, Type, TypeVar

import requests

BASE_URL = "http://www.sfu.ca/bin/wcm/course-outlines"
TERM = ("2025", "registration")

parser = argparse.ArgumentParser()
parser.add_argument("--dept", required=True)


def get_seating(n, c):
    param = n[:-5].lower().replace(' ', '-')
    c = c.lower()
    if "00" in c:
        c = c[0:2]
    url = f"https://coursys.sfu.ca/browse/info/2025sp-{param}-{c}"
    resp = requests.get(url)
    if not resp.ok:
        print(f"{url}: {resp.status_code}")
        sys.exit(-1)

    soup = BS(resp.text, "html.parser")
    field = soup.select_one(
        "#courseinfo > tbody:nth-child(1) > tr:nth-child(3) > td:nth-child(2)"
    )

    assert field, "couldn't find seating field"
    text = field.get_text(strip=True)
    match = re.match(r"(\d+) out of (\d+)(?: \((\d+) on waitlist\))?\s?\*?", text)

    match = re.match(r"(\d+) out of (\d+)(?: \((\d+) on waitlist\))?\s?\*?", text)

    if match:
        # Extracted values
        students_in = int(match.group(1))
        total_students = int(match.group(2))
        waitlist = int(match.group(3)) if match.group(3) else 0

        result = (students_in, total_students, waitlist)
        return result
    else:
        print("couldn't match ", field)
        sys.exit()

def seating_to_str(i, m, w):
    if w != 0:
        if i < 0.9 * m:
            # some courses have wait-lists, but lots of seats.
            return f"\033[32m{i}(+{w})/{m}\033[0m"
        if w < 20:
            return f"\033[33m{i}(+{w})/{m}\033[0m"
        else:
            return f"\033[31m{i}(+{w})/{m}\033[0m"
    else:
        return f"\033[32m{i}/{m}\033[0m"

def seat_str(n, c):
    return seating_to_str(*get_seating(n, c))

class D(Enum):
    M = "Mo"
    W = "We"
    F = "Fr"
    TU = "Tu"
    TH = "Th"

    def s(self):
        return self.value


class Course:
    def __init__(self, data) -> None:
        self.id = data["value"]
        self.name = data["title"]


class Section:
    def __init__(self, data) -> None:
        self.id = data["value"]
        self.name = data["title"]
        self.type = data["classType"]
        self.sec_code = data["sectionCode"]


class Schedule:
    def __init__(self, data) -> None:
        self.campus = data.get("campus", None)
        self.days = data.get("days", None)
        self.sectionCode = data.get("sectionCode", None)
        self.startTime = data.get("startTime", None)
        self.endTime = data.get("endTime", None)


class Outline:
    def __init__(self, data):
        info = data["info"]
        self.name = info.get("name")
        self.title = info.get("title")
        self.number = info.get("number")
        self.desc = info.get("description")
        self.section = info.get("section")
        self.type = info.get("type")
        self.outline_path = info.get("outlinePath")
        self.coreq = info.get("corequisites")
        self.prereq = info.get("prerequisites")
        self.dept = info.get("dep")
        self.level = info.get("degreeLevel")
        self.details = info.get("courseDetails")
        schedules = data.get("courseSchedule")
        if schedules:
            self.schedule = [Schedule(s) for s in schedules]
        else:
            self.schedule = None
        self.s_in = None
        self.s_out = None
        self.s_wait = None
    
    def set_seating(self):
        s_in, s_out, s_wait = get_seating(c.name, c.section)
        self.s_in = s_in
        self.s_out = s_out
        self.s_wait = s_wait

    def seat_str(self):
        if self.s_in is None:
            return ""
        else:
            s = f"[{seating_to_str(self.s_in, self.s_out, self.s_wait)}]"
            return s.ljust(24)

    def print_prereq(self):
        if self.prereq:
            return print(f"\t\tPrereq: {self.prereq}")
        else:
            return print("\t\tPrereq: None")


    def __str__(self) -> str:
        return f"{self.seat_str()}\033[1;35m{self.name}\033[0m {self.title}"

    __repr__ = __str__


T = TypeVar("T")


def parse_to(data, clazz: Type[T]) -> List[T]:
    parsed = []
    for datum in data:
        try:
            parsed.append(clazz(datum))
        except:
            pass
    return parsed


def query(*params):
    url = BASE_URL + "?" + "/".join(params)
    resp = requests.get(url)
    if not resp.ok:
        print(f"\033[31m{resp.status_code}:\033[0m {url}")
    return resp.json()


def load_cached_dept(dept):
    cache_file = f"cache/{dept}.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, "rb") as f:
            print(f"\033[32mFound cached data:\033[0m {cache_file}")
            return pickle.load(f)
    else:
        return None


def write_cached_dept(dept, data):
    if not os.path.exists("cache"):
        os.mkdir("cache")
    cache_file = f"cache/{dept}.pkl"
    with open(cache_file, "wb") as f:
        pickle.dump(data, f)
        print(f"\033[K\033[1;32mWrote cache:\033[0m {cache_file}")


def get_dept_data(dept):
    dept_data = load_cached_dept(dept)
    if dept_data is not None:
        return dept_data
    courses = parse_to(query(*TERM, dept), Course)
    course_outlines = []
    for i, course in enumerate(courses):
        course: Course
        print(f"\033[KLoading {dept}: {i}/{len(courses)}", end="\r")
        try:
            course_id = course.id
            sections = parse_to(query(*TERM, dept, course_id), Section)
            section = sections[0]
            section_id = section.id
            outline = Outline(query(*TERM, dept, course_id, section_id))
            if outline.level != "UGRD":
                print(f"\033[K\033[1;33mFiltered:\033[0m {outline} (not ugrad)")

            elif outline.type != "e":
                print(f"\033[K\033[1;33mFiltered:\033[0m {outline} (not enrollable)")
            else:
                print(f"\033[K\033[1;32mLoaded:\033[0m {outline}")
                course_outlines.append(outline)
        except Exception as e:
            print(f"\033[31mFailed. Skipping.\033[0m ({e})")
    dept_data = course_outlines
    if dept_data:
        write_cached_dept(dept, dept_data)
    return dept_data


if __name__ == "__main__":
    args = parser.parse_args()
    dept = args.dept
    data = get_dept_data(dept)

    def fu(data):
        return [x for x in data if x.schedule]

    def fc(data):
        return [x for x in data if x.schedule[0].campus == "Burnaby"]

    def ft(data):
        if args.dept == "cmpt":
            taken = [
                "105W",
                "120",
                "125",
                "210",
                "225",
                "276",
                "307",
                "310",
                "354",
                "361",
                "383",
                "471",
            ]
            return [x for x in data if x.number not in taken]
        if args.dept == "psyc":
            taken = ["100", "102"]
            return [x for x in data if x.number not in taken]
        return data

    def ftime(data):
        def ic(s1, s2, e1, e2):
            return not (e1 < s2 or e2 < s1)

        def t2m(s):
            s = s.split(":")
            return 60 * int(s[0]) + int(s[1])

        def tc(s: Schedule):
            d = s.days
            if D.M.s() in d or D.W.s() in d or D.F.s() in d:
                if ic(t2m("9:30"), t2m(s.startTime), t2m("10:20"), t2m(s.endTime)):
                    return True
            if D.TU.s() in d:
                if ic(t2m("11:30"), t2m(s.startTime), t2m("13:20"), t2m(s.endTime)):
                    return True
            if D.TH.s() in d:
                if ic(t2m("11:30"), t2m(s.startTime), t2m("12:20"), t2m(s.endTime)):
                    return True
            if D.F.s() in d:
                if ic(t2m("14:30"), t2m(s.startTime), t2m("17:20"), t2m(s.endTime)):
                    return True
            return False

        def possible(c):
            for s in c.schedule:
                if tc(s):
                    return False
            return True

        return [x for x in data if possible(x)]

    courses = ftime(ft(fc(fu(data))))
    for c in courses:
        c: Outline
        c.set_seating()
        print(c)
        c.print_prereq()
