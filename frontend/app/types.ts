export type SubmitJobParams = {
  prompt: string;
  maxPages?: number;
};

export type InteractionStep = {
  kind: string;
  selector?: string | null;
  count?: number;
  wait_ms?: number;
  value?: string | null;
  note?: string | null;
};

export type PaginationPlan = {
  mode: string;
  parameter?: string | null;
  template?: string | null;
  start?: number;
  step?: number;
};

export type ScrapePlan = {
  seed_url: string;
  fields: string[];
  description: string;
  extra_urls: string[];
  interactions: InteractionStep[];
  pagination?: PaginationPlan | null;
  requested_page_count?: number | null;
  notes: string[];
};

export type ScrapedItem = Record<string, string>;

export type FieldCoverage = Record<string, number>;

export type ScrapeMetadata = {
  item_count: number;
  source_urls: string[];
  field_coverage: FieldCoverage;
  [key: string]: unknown;
};

export type ScrapeJobResponse = {
  plan: ScrapePlan;
  items: ScrapedItem[];
  warnings: string[];
  errors: string[];
  metadata: ScrapeMetadata;
};
