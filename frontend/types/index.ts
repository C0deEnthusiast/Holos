export interface ScannedItem {
  id?: string;
  name: string;
  category: string;
  make?: string;
  model?: string;
  condition: string;
  confidence_score: number;
  estimated_price_usd: number;
  unit_price_usd?: string;
  resale_value_usd?: string;
  retail_replacement_usd?: string;
  insurance_replacement_usd?: string;
  price_basis?: string;
  estimated_dimensions?: string;
  bounding_box?: number[];
  thumbnail_url?: string;
  thumbnail_source?: string;
  original_image_url?: string;
  home_name?: string;
  room_name?: string;
  quantity?: number;
  is_set?: boolean;
  estimated_age_years?: number;
  condition_notes?: string;
  identification_basis?: string;
  auto_saved?: boolean;
  review_reason?: string;
  // Pipeline-specific (video scan)
  _source_frame?: number;
  _source_timestamp?: number;
}

export interface ScanResponse {
  success: boolean;
  api_version?: string;
  data: ScannedItem[];
  auto_saved: ScannedItem[];
  needs_review: ScannedItem[];
  summary: {
    total: number;
    auto_saved_count: number;
    needs_review_count: number;
    threshold: number;
  };
  pipeline?: {
    frames_extracted: number;
    frames_processed: number;
    duplicates_skipped: number;
    items_before_merge: number;
    unique_items: number;
    processing_time_sec: number;
    errors?: string[] | null;
  };
}

export interface SavedItem {
  id: string;
  user_id: string;
  name: string;
  category?: string;
  make?: string;
  model?: string;
  condition?: string;
  estimated_price_usd?: number;
  estimated_dimensions?: string;
  thumbnail_url?: string;
  original_image_url?: string;
  is_archived: boolean;
  home_name?: string;
  room_name?: string;
  quantity?: number;
  unit_price_usd?: string;
  resale_value_usd?: string;
  retail_replacement_usd?: string;
  insurance_replacement_usd?: string;
  price_basis?: string;
  confidence_score?: number;
  created_at?: string;
  updated_at?: string;
}

export interface EstateReport {
  success: boolean;
  report_date: string;
  owner_id: string;
  total_market_value: number;
  total_items: number;
  properties: Record<
    string,
    Record<
      string,
      {
        items: Array<{
          name: string;
          category?: string;
          make?: string;
          model?: string;
          price: number;
          resale_price_range?: string;
          retail_replacement_cost?: string;
          insurance_replacement_value?: string;
          condition?: string;
          thumbnail?: string;
        }>;
        subtotal: number;
        total_insurance_value: number;
      }
    >
  >;
}
