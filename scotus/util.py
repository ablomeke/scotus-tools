# Copyright (c) 2018  Floyd Terbo

import dateutil.parser
import sys
import unicodedata

PETITION_LINKS = set(["Petition", "Appendix", "Jurisdictional Statement"])
PETITION_TYPES = set(["certiorari", "mandamus", "habeas", "jurisdiction", "prohibition"])

def getTranslation(tt = {}):
  if not tt:
    # Translation table to strip unicode punctuation, but not things like section symbols
    tt = { i:None for i in xrange(sys.maxunicode)
               if unicodedata.category(unichr(i)).startswith('P') }

    # For some reason PyPDF2 resolves some text to the wrong code points
    tt[8482] = None # Single quotes
    tt[64257] = None  # Double quote open
    tt[64258] = None  # Double quote close
    tt[339] = None  # Endash
    tt[352] = None  # Emdash
  return tt

class SCOTUSError(Exception): pass

class CasenameError(SCOTUSError):
  def __init__ (self, docket):
    self.docket = docket
  def __str__ (self):
    return "Unable to create case name for %s" % (self.docket)

class CaseTypeError(SCOTUSError):
  def __init__ (self, docket):
    self.docket = docket
  def __str__ (self):
    return "Unable to determine case type for %s" % (self.docket)


class CourtMatch(object):
  def __init__ (self, *args):
    self.names = args
    self.start = []
    self.partial = None

  def __eq__ (self, val):
    if not val:
      return False
    if val in self.names:
      return True
    if self.start:
      for frag in self.start:
        if val.startswith(frag):
          return True
    if self.partial and val.count(self.partial):
      return True
    return False

  def __ne__ (self, val):
    return not self == val

  def setStart (self, val):
    self.start.append(val)
    return self

  def setPartial (self, val):
    self.partial = val
    return self


class DocketStatusInfo(object):
  def __init__ (self, docket_obj):
    self.docket_date = None
    self.capital = False
    self.casename = None
    self.casetype = None
    self.lowercourt = None
    self.lowercourt_docket = None
    self.lowercourt_decision_date = None

    self.related = []

    self.granted = False
    self.grant_date = None
    self.argued = False
    self.argued_date = None
    self.distributed = []
    self.dismissed = False
    self.dismiss_date = None
    self.denied = False
    self.deny_date = None
    self.judgment_issued = False
    self.judgment_date = None
    self.gvr = False
    self.gvr_date = None

    self.attys_petitioner = []
    self.attys_respondent = []

    self._build(docket_obj)

  def _build (self, docket_obj):
    try:
      self.docket_date = dateutil.parser.parse(docket_obj["DocketedDate"])
      self.capital = docket_obj["bCapitalCase"]
      self.casename = buildCasename(docket_obj)
      self.casetype = getCaseType(docket_obj)

      if "Petitioner" in docket_obj:
        for info in docket_obj["Petitioner"]:
          self.attys_petitioner.append(info["Attorney"])

      if "Respondent" in docket_obj:
        for info in docket_obj["Respondent"]:
          self.attys_respondent.append(info["Attorney"])

      if "RelatedCaseNumber" in docket_obj:
        for rc in docket_obj["RelatedCaseNumber"]:
          rcnl = rc["DisplayCaseNumber"].split(",")
          for rcn in rcnl:
            (tstr, dstr) = rcn.split("-")
            self.related.append((int(tstr), int(dstr), rc["RelatedType"]))

      if "LowerCourt" in docket_obj and docket_obj["LowerCourt"]:
        self.lowercourt = docket_obj["LowerCourt"].strip()
        try:
          self.lowercourt_docket = docket_obj["LowerCourtCaseNumbers"]
          self.lowercourt_decision_date = dateutil.parser.parse(docket_obj["LowerCourtDecision"]).date()
        except KeyError:
          pass

      for event in docket_obj["ProceedingsandOrder"]:
        etxt = event["Text"]
        if etxt.startswith("DISTRIBUTED"):
          confdate = dateutil.parser.parse(etxt.split()[-1]).date()
          edate = dateutil.parser.parse(event["Date"]).date()
          self.distributed.append((edate, confdate))
        elif etxt == "Petition GRANTED.":
          self.granted = True
          self.grant_date = dateutil.parser.parse(event["Date"]).date()
        elif etxt.count("GRANTED"):
          statements = etxt.split(".")
          gs = [x for x in statements if x.count("GRANTED")][0]
          if gs.count("expedite consideration"):
            continue
          self.granted = True
          self.grant_date = dateutil.parser.parse(event["Date"]).date()
          if etxt.count("VACATED") and etxt.count("REMANDED"):
            self.gvr = True
            self.gvr_date = self.grant_date
        elif etxt.startswith("Argued."):
          self.argued = True
          self.argued_date = dateutil.parser.parse(event["Date"]).date()
        elif etxt.startswith("Petition Dismissed"):
          self.dismissed = True
          self.dismiss_date = dateutil.parser.parse(event["Date"]).date()
        elif etxt.startswith("Petition DENIED"):
          self.denied = True
          self.deny_date = dateutil.parser.parse(event["Date"]).date()
        elif etxt == "JUDGMENT ISSUED.":
          self.judgment_issued = True
          self.judgment_date = dateutil.parser.parse(event["Date"]).date()
        elif etxt.startswith("Adjudged to be AFFIRMED."):
          self.judgment_issued = True
          self.judgment_date = dateutil.parser.parse(event["Date"]).date()
        elif etxt.startswith("Judgment REVERSED"):
          self.judgment_issued = True
          self.judgment_date = dateutil.parser.parse(event["Date"]).date()
    except Exception:
      print "Exception in case: %s" % (docket_obj["CaseNumber"])
      raise

  @property
  def pending (self):
    if self.dismissed or self.denied or self.judgment_issued or self.gvr:
      return False
    return True

  def getFlagString (self):
    flags = []
    if self.capital: flags.append("CAPITAL")
    if self.related: flags.append("RELATED")
    if self.argued: flags.append("ARGUED")
    if self.gvr:
      flags.append("GVR")
    else:
      if self.granted: flags.append("GRANTED")
      if self.dismissed: flags.append("DISMISSED")
      if self.denied: flags.append("DENIED")
      if self.judgment_issued: flags.append("ISSUED")
    if flags:
      return "[%s]" % (", ".join(flags))
    else:
      return ""
  
def getPdfWords (path):
  import PyPDF2

  tt = getTranslation()
  wd = {}
  with open(path, "rb") as fo:
    reader = PyPDF2.PdfFileReader(fo)
    for pno,page in enumerate(range(reader.numPages)):
      try:
        clean_text = reader.getPage(page).extractText().translate(tt)
        wd[pno] = clean_text.split()
      except KeyError: # Some PDF pages don't have /Contents
        continue
  return wd


def getCaseType (docket_obj):
  if ("PetitionerTitle" in docket_obj) and ("RespondentTitle" in docket_obj):
    # TODO: Yes yes, we'll fix it later
    return "certiorari"

  founditem = None
  for item in docket_obj["ProceedingsandOrder"]:
    try:
      if item["Text"].startswith("Petition"):
        for ptype in PETITION_TYPES:
          if item["Text"].count(ptype):
            return ptype
      for link in item["Links"]:
        if link["Description"] == "Petition":
          # TODO: This does not tend to capture original actions or mandatory appeals
          founditem = item
          break
      if founditem:
        break
    except KeyError:
      continue

  if not founditem:
    raise CaseTypeError(docket_obj["CaseNumber"].strip())

  match = list(set(founditem["Text"].split()) & PETITION_TYPES)
  return match[0]


def buildCasename (docket_obj):
  casetype = getCaseType(docket_obj)

  casename = ""
  try:
    # TODO: This is all horrible, but works for most cases
    if casetype in ["mandamus", "habeas"]:
      pt = docket_obj["PetitionerTitle"]
      parts = pt.split(",")
      if parts[-1].count("Petitioner"):
        casename = ",".join(parts[:-1])
      else:
        casename = pt
    else:
      pt = docket_obj["PetitionerTitle"]
      if pt[:5] == "In Re":
        parts = pt.split(",")
        if parts[-1].count("Petitioner"):
          casename = ",".join(parts[:-1])
        else:
          casename = pt
      else:
        petitioner = docket_obj["PetitionerTitle"][:-12]  # Remove ", Petitioner" from metadata
        casename = "%s v. %s" % (petitioner, docket_obj["RespondentTitle"])
  except Exception:
    raise CasenameError(docket_obj["CaseNumber"].strip())

  return casename


def ngrams (wlist, n):
  output = {}
  for i in range(len(wlist)-n+1):
    gram = ' '.join(wlist[i:i+n])
    output.setdefault(gram, 0)
    output[gram] += 1
  return output

