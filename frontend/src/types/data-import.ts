export interface DataImportFile {
  file_id: string
  name: string
  size: number
  modified: string
}

export interface DataImportParseResult {
  file_id: string
  columns: string[]
  dtypes: Record<string, string>
  row_count: number
  sample: Record<string, any>[]
  detected: {
    date_cols: string[]
    numeric_cols: string[]
    categorical_cols: string[]
  }
}

export interface ChartOutput {
  dir: string
  chart_type: string
  data_points: number
  html_path: string
  relative_url: string
  created_at: string
}