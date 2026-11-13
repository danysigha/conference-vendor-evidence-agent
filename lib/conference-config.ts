export const CONFERENCE = {
  id: "gai_boston_2026",
  name: "Generative AI Summit Boston 2026",
  date: "October 29, 2026",
  venue: "The Westin Boston Seaport",
  partnerCount: 28,
  flyerBackedCompanyCount: 5,
  flyerDocumentCount: 6,
  sessionCount: 31,
  speakerRecordCount: 47,
  capabilityClaimCount: 281,
  companyPageCount: 67,
  sourceUrl:
    "https://world.aiacceleratorinstitute.com/location/boston/partners",
} as const;

export const CONFERENCE_DATA_MOUNT = "/mnt/session/uploads/conference";
export const CONFERENCE_DOCUMENTS_CSV = "exhibitor_documents.csv";
export const CONFERENCE_EXHIBITORS_CSV = "exhibitors.csv";
export const CONFERENCE_WORKBOOK_FILENAME =
  "Generative_AI_Summit_Boston_2026_exhibitors.xlsx";
