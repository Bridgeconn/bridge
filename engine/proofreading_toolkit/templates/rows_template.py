# rows_<book>.py — the findings for one book, written by the checker (Claude) after reading every verse.
# One R(...) call = one finding at one verse. Fields, in order:
#   chapter ("Intro" for the introduction), verse ("" for intro), Issue Type, Priority Category, Severity (High/Medium/Low),
#   Confidence (High/Medium/Low/Reviewer decision), Original (exact text as it stands; "\\s ..." for a heading),
#   Suggested Correction (clean target-language text only, or "" for a decision), Explanation (plain English),
#   Reference note (short reference-Bible phrase with verse), Reviewer decision needed ("No" / "Review" / "Yes")
ROWS = []
def R(*a): ROWS.append(a)
I = "Intro"
TITLE = "Book name"
N = "Introduction only; no reference counterpart."
# R(I, "", "Possible typo", "Typo", "Low", "High", "wrong word", "right word", "Why.", N, "No")
# R(3, 16, "Source comparison", "Source", "Medium", "High", "exact words", "proposed words", "What is wrong and its effect.", "REF 3:16 …", "Review")
# R(3, 17, "Heading", "Heading", "Low", "High", "\\s heading text with typo", "", "Typo. Suggested: corrected heading", "", "Yes")
TYPE_NOTES = {}          # issue type -> one-line note shown in the workbook summary (also 'nothing found' notes)
REVIEWED = "whole book, every verse read against the reference, and the introduction"
REJECTED = []            # (lead, why not reported) — leads checked and found to be house style or correct
# NO_MINORITY = True     # switch off automatic minority-spelling rows for this book
