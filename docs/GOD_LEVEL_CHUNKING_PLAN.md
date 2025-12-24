# GOD-LEVEL Chunking Strategy for Aurora RAG

## Objective
Extract EVERY piece of information from Google Sheets - ALL sheets, ALL columns, ALL rows, ALL cells.

## Current State
- ✅ Reads main event sheet (events_rag_simple)
- ✅ Reads FAQs sheet
- ✅ Creates ~111 chunks from 20 events
- ⚠️ Hardcoded column names
- ⚠️ Limited to 2 sheets

## God-Level Enhancement Plan

### 1. **Multi-Sheet Discovery**
```python
# Auto-discover ALL sheets in the Google Sheets document
all_worksheets = spreadsheet.worksheets()
for worksheet in all_worksheets:
    if worksheet.title not in ['Template', 'Archive']:  # Skip meta sheets
        data = worksheet.get_all_records()
        process_sheet(worksheet.title,data)
```

### 2. **Dynamic Column Extraction**
```python
# For EACH sheet, extract ALL columns dynamically
df = pd.DataFrame(data)
all_columns = df.columns.tolist()

for column in all_columns:
    # Create chunks for each column's unique values
    # No hardcoding - works with ANY column name!
```

### 3. **Cell-Level Granularity**
```python
# For EACH row in EACH sheet:
for idx, row in df.iterrows():
    # CHUNK 1: Complete row (all columns)
    full_row_text = format_row_as_text(row, all_columns)
    
    # CHUNK 2: Each non-empty cell as separate chunk
    for col in all_columns:
        if row[col] and row[col] != 'N/A':
            cell_chunk = f"{col}: {row[col]}"
            # This catches EVERYTHING!
```

### 4. **Cross-Sheet Relationships**
```python
# Link related information across sheets
# Example: Events → FAQs → Venues
if 'event_name' in events_sheet and 'event_name' in faqs_sheet:
    join_and_create_chunks(events_sheet, faqs_sheet, on='event_name')
```

### 5. **Metadata Preservation**
```python
# EVERY chunk includes:
{
    "text": "...",  # Actual content
    "meta": {
        "sheet_name": "events_rag_simple",
        "row_number": 5,
        "columns_included": ["event_name", "topics"],
        "original_values": {...},  # Full row data
        "chunk_type": "multi_column",
        "is_latest": True
    }
}
```

## Implementation Strategy

### Phase 1: Sheet Discovery (20 lines)
```python
def discover_all_sheets(self):
    \"\"\"Get ALL sheets from Google Sheets\"\"\"
    return [ws for ws in self.spreadsheet.worksheets() 
            if ws.title not in ['Template', 'Archive', '_meta']]
```

### Phase 2: Universal Column Handler (30 lines)
```python
def extract_all_columns(self, df, sheet_name):
    \"\"\"Create chunks from ALL columns, regardless of name\"\"\"
    chunks = []
    for  col in df.columns:
        # Column-specific chunks
        unique_values = df[col].dropna().unique()
        if len(unique_values) > 0:
            chunks.append({
                "text": f"Available {col} values: {', '.join(map(str, unique_values))}",
                "meta": {"type": f"column_{col}", "sheet": sheet_name}
            })
    return chunks
```

### Phase 3: Row-Level Chunking (40 lines)
```python
def chunk_each_row(self, df, sheet_name):
    \"\"\"Create multiple chunks per row for maximum retrieval\"\"\"
    chunks = []
    for idx, row in df.iterrows():
        # Chunk 1: Full row
        full_text = " | ".join([f"{col}: {row[col]}" for col in df.columns if pd.notna(row[col])])
        chunks.append({"text": full_text, "meta": {"type": "row_complete", "sheet": sheet_name, "row": idx}})
        
        # Chunk 2: Each non-empty cell
        for col in df.columns:
            if pd.notna(row[col]) and str(row[col]).strip():
                chunks.append({
                    "text": f"{col}: {row[col]}",
                    "meta": {"type": "cell_individual", "column": col, "sheet": sheet_name}
                })
    return chunks
```

### Phase 4: Aggregation Chunks (20 lines)
```python
def create_summary_chunks(self, all_sheets_data):
    \"\"\"Cross-sheet summaries\"\"\"
    chunks = []
    
    # Total count across all sheets
    total_rows = sum(len(df) for df in all_sheets_data.values())
    chunks.append({
        "text": f"Total information: {total_rows} rows across {len(all_sheets_data)} sheets",
        "meta": {"type": "global_summary"}
    })
    
    return chunks
```

## Expected Results

### Before (Current - 111 chunks):
- ✅ 20 events
- ✅ ~5 chunks per event
- ✅ 1-2 sheets

### After (GOD-LEVEL - 500+ chunks):
- ✅ ALL sheets (events, FAQs, venues, contacts, etc.)
- ✅ Every column captured
- ✅ Every row multiple chunks
- ✅ Every non-empty cell indexed
- ✅ Cross-sheet summaries
- ✅ Column-value lists
- ✅ Future-proof for ANY new columns/sheets

## Benefits

1. **Zero Configuration**: Add new columns to Google Sheets → Automatically indexed
2. **Complete Coverage**: Impossible to miss information
3. **Flexible Querying**: Can search by ANY field
4. **Future-Proof**: Works for Aurora 2026, 2027, etc.
5. **No Hardcoding**: Dynamic column detection

## Retrieval Example

**User Query**: "Workshop on day 3 at Academic Block"

**Chunks Retrieved** (from 500+ pool):
1. Event day-specific chunk: "CONVenient - Day 3"
2. Venue chunk: "Academic Block - Room 101"
3. Cell chunk: "venue: Academic Block - Room 101"
4. Row chunk: Full event details for Day 3
5. Cross-reference chunk: Day 3 events summary

**Result**: 5 relevant chunks instead of 1 → Better context for LLM!

## Code Size Estimate
- Current chunking: ~200 lines (hardcoded)
- GOD-LEVEL chunking: ~150 lines (dynamic + universal)
- **Less code, more power!**
