#!/usr/bin/python3
# (c) Bernhard Tittelbach, 2015-2017, AGPLv3


import copy
import datetime
import os
import re
from typing import List

dateformat_hledger_csvexport_ = "%Y/%m/%d"


class DifferentCurrency(Exception):
    pass


class Amount:
    def __init__(self, quantity, currency):
        self.quantity = float(quantity)
        self.currency = currency.strip()
        self.totalprice = None
        self.perunitprice = None

    def addTotalPrice(self, amount):
        if amount is None:
            return self
        self.totalprice = copy.copy(amount).makePositive()
        self.perunitprice = Amount(
            amount.quantity / self.quantity, amount.currency
        ).makePositive()
        return self

    def addPerUnitPrice(self, amount):
        if amount is None:
            return self
        self.totalprice = Amount(
            amount.quantity * self.quantity, amount.currency
        ).makePositive()
        self.perunitprice = copy.copy(amount).makePositive()
        return self

    def add(self, amount):
        if self.quantity == 0:
            self.quantity = amount.quantity
            self.currency = amount.currency
            self.totalprice = amount.totalprice
            self.perunitprice = amount.perunitprice
            return self
        elif amount.quantity == 0:
            return self
        if self.currency != amount.currency:
            raise DifferentCurrency
        if not self.totalprice is None or not amount.totalprice is None:
            if self.totalprice is None:
                if amount.perunitprice is None:
                    self.perunitprice = Amount(
                        amount.totalprice.quantity / amount.quantity,
                        amount.totalprice.currency,
                    )
                else:
                    self.perunitprice = copy.copy(amount.perunitprice)
                self.totalprice = Amount(
                    self.perunitprice.quantity
                    * (self.quantity + amount.quantity),
                    amount.totalprice.currency,
                )
            elif amount.totalprice is None:
                self.totalprice.quantity = self.perunitprice.quantity * (
                    self.quantity + amount.quantity
                )
            else:
                if self.totalprice.currency != amount.totalprice.currency:
                    raise DifferentCurrency
                self.totalprice.quantity += (
                    amount.sgn() * amount.totalprice.quantity
                )
                try:
                    self.perunitprice.quantity = self.totalprice.quantity / (
                        self.quantity + amount.quantity
                    )
                except ZeroDivisionError:
                    self.perunitprice.quantity = (
                        self.perunitprice.quantity
                        + amount.perunitprice.quantity
                    ) / 2
        self.quantity += amount.quantity
        return self

    def __add__(self, amount):
        return self.add(amount)

    def isPositiv(self):
        return self.quantity >= 0

    def sgn(self):
        if self.quantity == 0:
            return 0
        if self.isPositiv():
            return 1
        else:
            return -1

    def flipSign(self):
        self.quantity *= -1
        return self

    def makePositive(self):
        if not self.isPositiv():
            self.flipSign()
        return self

    def copy(self):
        return copy.deepcopy(self)

    def __str__(self):
        "Format unit/currency quantity as a string."
        a = "%.4f" % (self.quantity)
        a = "{} {}".format(
            a.rstrip("0").rstrip(".,"),
            self.currency,
        )  # unfortunately %g does not do the correct thing so we need to use rstrip
        if not self.totalprice is None:
            if not self.perunitprice is None and self.quantity == 0:
                a += " @ " + str(self.perunitprice)
            else:
                a += " @@ " + str(self.totalprice)
        return a


class NoAmount(Amount):
    def __init__(self):
        self.quantity = 0
        self.currency = ""
        self.totalprice = None

    def __str__(self):
        return ""


class Posting:
    def __init__(
        self, account, amount, commenttags=[], assertamount=None, virtual=False
    ):
        self.account = account.strip()
        self.amount = amount if not amount is None else NoAmount()
        if not isinstance(self.amount, Amount):
            raise TypeError("Expected amount to be of type Amount.")
        self.tags = {}
        self.commenttags = []
        self.virtual = virtual
        self.post_posting_assert_amount = (
            None if isinstance(assertamount, NoAmount) else assertamount
        )
        if isinstance(commenttags, str):
            self.commenttags.append(commenttags.strip())

    def addComment(self, comment):
        self.commenttags.append(comment.strip())
        return self

    def addTag(self, tag, taginfo=""):
        if not isinstance(taginfo, str):
            taginfo = str(taginfo)
        taginfo = taginfo.strip(" ,\t\n").replace(",", "%2C")
        if tag.find(" ") >= 0:
            raise ValueError("Found non negative number of spaces.")
        if taginfo.find(",") >= 0:
            raise ValueError("Found non negative number of commas.")
        self.tags[tag] = taginfo
        return self

    def setDate(self, date):
        if date is None or date == "":
            return self
        elif isinstance(date, datetime.datetime) or isinstance(
            date, datetime.date
        ):
            date = date.strftime(dateformat_hledger_csvexport_)
        return self.addTag("date", date)

    def strAligned(self, maxacctlen, maxamountlen):
        amtstr = self.__formatAmount()
        if len(amtstr) == 0:
            return f"    {self.account}{self.__formatComment()}"
        else:
            return "{:{fill}<4}{:{fill}<{maxacctlen}}{:{fill}<5}{:{fill}>{maxamountlen}}{commentstr}".format(
                "",
                self.__formatAccount(),
                "",
                amtstr,
                fill=" ",
                maxacctlen=maxacctlen,
                maxamountlen=maxamountlen,
                commentstr=self.__formatComment(),
            )

    def __formatAccount(self):
        return "(%s)" % self.account if self.virtual else self.account

    def __formatComment(self):
        # it's a good idea to always close a tag with a comma. Reduces mistakes during manual edit
        # NOTE: tags come first, comment comes later on postings. Otherwise we would have to check the commenttags for stray ':'
        commenttags = [
            "%s:%s," % x for x in sorted(self.tags.items())
        ] + self.commenttags
        if len(commenttags) == 0:
            return ""
        return (
            "\n"
            if self.amount is None or isinstance(self.amount, NoAmount)
            else ""
        ) + "\n".join(
            map(
                lambda l: "{:{fill}<4}; {}".format("", l, fill=" "), commenttags
            )
        )

    def __formatAmount(self):
        rv = (
            ""
            if self.amount is None or isinstance(self.amount, NoAmount)
            else str(self.amount)
        )
        if not self.post_posting_assert_amount is None:
            rv += " = " + str(self.post_posting_assert_amount)
        return rv

    def __str__(self):
        return self.strAligned(0, 0)


class Transaction:
    def __init__(self, name="", date=None):
        self.setDate(date)
        self.desc = []
        self.name = name.strip()
        self.code = None
        self.comments = []
        self.postings = []
        self.tags = {}

    def copy(self):
        return copy.deepcopy(self)

    def __lt__(self, o):
        return self.date + str(self.code) < o.date + str(o.code)

    # description are journal comments before an transaction (not very aptly named... TODO)
    def addDescription(self, desc):
        self.desc += [desc.strip()]
        return self

    # comment is next to transaction name or after transaction name
    def addComment(self, comment):
        self.comments.append(comment)
        return self

    def addTag(self, tag, taginfo=""):
        if not isinstance(taginfo, str):
            taginfo = str(taginfo)
        taginfo = taginfo.strip(" ,\t\n").replace(",", "%2C")
        if tag.find(" ") >= 0:
            raise ValueError("Found non negative number of spaces.")
        if taginfo.find(",") >= 0:
            raise ValueError("Found non negative number of commas.")
        self.tags[tag] = taginfo
        return self

    def setDate(self, date):
        if date is None or date == "":
            self.date = datetime.date.today().strftime(
                dateformat_hledger_csvexport_
            )
        elif isinstance(date, datetime.datetime) or isinstance(
            date, datetime.date
        ):
            self.date = date.strftime(dateformat_hledger_csvexport_)
        else:
            self.date = date
        return self

    def initTransaction(self, date, name, code=None, commenttags=""):
        self.name = name.strip()
        self.code = code.strip() if isinstance(code, str) else code
        separateAndAddCommentAndTags(commenttags, self.addComment, self.addTag)
        self.setDate(date)
        return self

    def addPosting(self, posting):
        if not isinstance(posting, Posting):
            raise TypeError("Expected posting to be of type Posting.")
        self.postings.append(posting)
        return self

    def isEmpty(self):
        return self.name == "" and len(self.postings) == 0

    def __str__(self):
        lines = []
        commenttags = []
        # put first comment line right next to transaction and tags after that
        if len(self.comments) > 0:
            commenttags.append(self.comments[0])
            if self.comments[0].find(":") > -1 and self.comments[0][-1] != ",":
                # oh oh, this would be interpreted as a unclosed tag, hiding the next tag after it, so we close it!
                self.comments[0] += ","
        # it's a good idea to always close a tag with a comma. Reduces mistakes during manual edit.:w
        commenttags += ["%s:%s," % x for x in sorted(self.tags.items())]
        if len(commenttags) > 0:
            commenttags.insert(0, ";")
        lines += map(lambda s: "; %s" % s, self.desc)
        lines.append(
            " ".join(
                filter(
                    len,
                    [
                        self.date,
                        (
                            "(%s)" % self.code
                            if not self.code is None and len(self.code) > 0
                            else ""
                        ),
                        self.name,
                    ]
                    + commenttags,
                )
            )
        )
        if len(self.comments) > 1:  # are there even more comments?
            lines += map(lambda s: "    ; %s" % s, self.comments[1:])
        if len(self.postings) > 0:
            maxacctlen = max([len(p.account) for p in self.postings])
            maxamountlen = max([len(str(p.amount)) for p in self.postings])
            lines += [
                p.strAligned(maxacctlen, maxamountlen) for p in self.postings
            ]
        return "\n".join(lines)


re_amount_str_3captures = (
    r"([€$]|[a-zA-Z]+)?\s*((?:-\s?)?[0-9.,]+)\s*([€$]|[a-zA-Z]+)?"
)
re_account_str = r"(?:[^ \t\n\r\f\v;]| [^ \t\n\r\f\v;])+"
re_journalcommentline = re.compile(r"^;(.+)$")
re_commentline = re.compile(r"^\s\s+;(.+)$")
re_transaction = re.compile(
    r"^([0-9][-0-9/]+)(?:=[-0-9/]+)?\s+(?:\((.+)\)\s+)?([^;]*)(?:\s*;(.+))?$"
)
re_posting = re.compile(
    r"^\s\s+("
    + re_account_str
    + r")(?:\s\s+"
    + re_amount_str_3captures
    + r"(?:\s*(@@?)\s*"
    + re_amount_str_3captures
    + r")?(?:\s*=\s*"
    + re_amount_str_3captures
    + r")?)?(?:\s+;(.+))?"
)
re_include = re.compile(r"^include\s+(.+)\s*$")
re_commentblock_begin = re.compile(r"^comment\s*$")
re_commentblock_end = re.compile(r"^end comment\s*$")
# re_tags_ = re.compile("(?:\s|^)(\S+):(\S*)") # old non-hledger-format-conform tag parser. Once could use this and print.py to fix files with broken tags
re_tags_ = re.compile(r"(?:\s|^)(\S+):([^,]+)?(?:,|$)")


def parseAmount(c1, quantity, c2):
    if c1 is None and quantity is None and c2 is None:
        return NoAmount()
    currency = c2 if c1 is None else c1
    if currency is None:
        currency = ""
    cp = quantity.find(",")
    dp = quantity.find(".")
    if cp >= 0 and dp >= 0:
        if dp > cp:
            quantity = quantity.replace(",", "")
        else:
            quantity = quantity.replace(".", "")
    quantity = quantity.replace(",", ".")
    return Amount(quantity, currency)


def separateAndAddCommentAndTags(commenttagstr, f_addcomment, f_addtag):
    if not isinstance(commenttagstr, str):
        return
    if len(commenttagstr) == 0:
        return
    for t, a in re_tags_.findall(commenttagstr):
        f_addtag(t, a)
    cmt = re_tags_.sub("", commenttagstr).strip()
    if len(cmt) > 0:
        f_addcomment(cmt)


def import_include_path_v2(*, match, journal, journal_reader, parent_path: str):
    """Process an include path, combining it with the parent path if relative,
    and validating existence if absolute.

    Args:
        match: Match object containing the include path
        journal: Existing journal content to append to
        journal_reader: Reader object (e.g., file or StringIO)
        parent_path: Parent directory path of the original file
    """
    # Try to build include path relative to journal reader's directory
    try:
        include_path = os.path.join(
            os.path.split(journal_reader.name)[0], match.group(1)
        )
    except AttributeError:
        include_path = match.group(1)

    # Determine if we need to combine with parent_path
    if parent_path != os.path.dirname(include_path):
        absolute_import_path = os.path.join(parent_path, include_path)
    else:
        absolute_import_path = include_path

    # Check if the file exists and process it
    if os.path.isfile(absolute_import_path):
        new_parent_path = os.path.dirname(absolute_import_path)

        with open(absolute_import_path) as include_file:
            journal += parseJournal(
                jreader=include_file, parent_path=new_parent_path
            )
        return journal
    else:
        raise ValueError(
            f"ERROR: Could not find include file: {include_path} at"
            f" absolute_import_path={absolute_import_path}"
        )


def parseJournal(*, jreader, parent_path: str) -> List[Transaction]:
    journal: List[Transaction] = []
    within_commentblock = False
    for line in jreader:
        line = line.strip("\n\r")

        if is_end_of_commentblock(line):
            within_commentblock = False
            continue
        if within_commentblock:
            continue
        if is_start_of_commentblock(line):
            within_commentblock = True
            continue

        if process_journal_commentline(line, journal):
            continue

        if process_commentline(line, journal):
            continue

        if process_transaction(line, journal):
            continue

        if process_posting(line, journal):
            continue

        if process_include(line, journal, jreader, parent_path):
            continue

    return journal


def is_end_of_commentblock(line: str) -> bool:
    return not re_commentblock_end.match(line) is None


def is_start_of_commentblock(line: str) -> bool:
    return not re_commentblock_begin.match(line) is None


def process_journal_commentline(line: str, journal: list) -> bool:
    m = re_journalcommentline.match(line)
    if m is not None:
        if len(journal) == 0 or not journal[-1].isEmpty():
            journal.append(Transaction())
        journal[-1].addDescription(m.group(1))
        return True
    return False


def process_commentline(line: str, journal: list) -> bool:
    m = re_commentline.match(line)
    if m is not None:
        if len(journal) == 0:
            journal.append(Transaction())
        if len(journal[-1].postings) == 0:
            separateAndAddCommentAndTags(
                m.group(1), journal[-1].addComment, journal[-1].addTag
            )
        else:
            separateAndAddCommentAndTags(
                m.group(1),
                journal[-1].postings[-1].addComment,
                journal[-1].postings[-1].addTag,
            )
        return True
    return False


def process_transaction(line: str, journal: list) -> bool:
    m = re_transaction.match(line)
    if m is not None:
        if len(journal) == 0 or not journal[-1].isEmpty():
            journal.append(Transaction())
        journal[-1].initTransaction(*m.group(1, 3, 2, 4))

        return True
    return False


def process_posting(line: str, journal: list) -> bool:
    m = re_posting.match(line)
    if m is not None:
        amt = parseAmount(*m.group(2, 3, 4))
        if m.group(5) == "@":
            amt.addPerUnitPrice(parseAmount(*m.group(6, 7, 8)))
        elif m.group(5) == "@@":
            amt.addTotalPrice(parseAmount(*m.group(6, 7, 8)))
        post_posting_assert_amount = parseAmount(*m.group(9, 10, 11))
        if len(journal) > 0:
            journal[-1].addPosting(
                Posting(
                    m.group(1), amt, assertamount=post_posting_assert_amount
                )
            )
            separateAndAddCommentAndTags(
                m.group(12),
                journal[-1].postings[-1].addComment,
                journal[-1].postings[-1].addTag,
            )
        return True
    return False


def process_include(
    line: str, journal: list, jreader, parent_path: str
) -> bool:
    m = re_include.match(line)
    if m is not None:
        import_include_path_v2(
            match=m,
            journal=journal,
            journal_reader=jreader,
            parent_path=parent_path,
        )
        return True
    return False
