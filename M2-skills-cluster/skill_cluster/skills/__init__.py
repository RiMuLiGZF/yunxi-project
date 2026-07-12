from __future__ import annotations

"""内置技能实现."""

from skill_cluster.skills.calendar import CalendarSkill
from skill_cluster.skills.contact import ContactSkill
from skill_cluster.skills.data_analysis import DataAnalysisSkill
from skill_cluster.skills.doc_proc import DocProcSkill
from skill_cluster.skills.finance import FinanceSkill
from skill_cluster.skills.flashcard import FlashcardSkill
from skill_cluster.skills.fulltext_search import FulltextSearchSkill
from skill_cluster.skills.goal import GoalSkill
from skill_cluster.skills.habit import HabitSkill
from skill_cluster.skills.journal import JournalSkill
from skill_cluster.skills.mood import MoodSkill
from skill_cluster.skills.notify import NotifySkill
from skill_cluster.skills.tide_memory import TideMemorySkill
from skill_cluster.skills.todo import TodoSkill
from skill_cluster.skills.translate import TranslateSkill
from skill_cluster.skills.web_fetch import WebFetchSkill

__all__ = [
    "CalendarSkill",
    "ContactSkill",
    "DataAnalysisSkill",
    "DocProcSkill",
    "FinanceSkill",
    "FlashcardSkill",
    "FulltextSearchSkill",
    "GoalSkill",
    "HabitSkill",
    "JournalSkill",
    "MoodSkill",
    "NotifySkill",
    "TideMemorySkill",
    "TodoSkill",
    "TranslateSkill",
    "WebFetchSkill",
]
