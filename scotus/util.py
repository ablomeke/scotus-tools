# Copyright (c) 2018  Floyd Terbo

PETITION_LINKS = set(["Petition", "Appendix", "Jurisdictional Statement"])
PETITION_TYPES = set(["certiorari", "mandamus", "habeas", "jurisdiction", "prohibition"])

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
    self.start = None
    self.partial = None

  def __eq__ (self, val):
    if val in self.names:
      return True
    if self.start and val.startswith(self.start):
      return True
    if self.partial and val.count(self.partial):
      return True
    return False

  def __ne__ (self, val):
    return not self == val

  def setStart (self, val):
    self.start = val
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

    self.granted = False
    self.grant_date = None
    self.argued = False
    self.argued_date = None
    self.distributed = []
    self.dismissed = False
    self.dismiss_date = None
    self.denied = False
    self.deny_date = None

    self._build(docket_obj)

  def _build (self, docket_obj):
    self.docket_date = dateutil.parser.parse(docket_obj["DocketedDate"])
    self.capital = docket_obj["bCapitalCase"]
    self.casename = util.buildCasename(docket_obj)
    self.casetype = util.getCaseType(docket_obj)

    for event in docket_obj["ProceedingsandOrder"]:
      etxt = event["Text"]
      if etxt.startswith("DISTRIBUTED"):
        confdate = dateutil.parser.parse(etxt.split()[-1])
        edate = dateutil.parser.parse(event["Date"])
        self.distributed.append((edate, confdate))
      elif etxt == "Petition GRANTED.":
        self.granted = True
        self.grant_date = dateutil.parser.parse(event["Date"])
      elif etxt.startswith("Argued."):
        self.argued = True
        self.argued_date = dateutil.parser.parse(event["Date"])
      elif etxt.startswith("Petition Dismissed"):
        self.dismissed = True
        self.dismiss_date = dateutil.parser.parse(event["Date"])
      elif etxt.startswith("Petition DENIED"):
        self.denied = True
        self.deny_date = dateutil.parser.parse(event["Date"])

  def getFlagString (self):
    flags = []
    if self.capital: flags.append("CAPITAL")
    if self.granted: flags.append("GRANTED")
    if self.argued: flags.append("ARGUED")
    if self.dismissed: flags.append("DISMISSED")
    if self.denied: flags.append("DENIED")
    if flags:
      return "[%s]" % (", ".join(flags))
    else:
      return ""
  

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
