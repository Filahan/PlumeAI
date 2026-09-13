/** The one grid the Tools table is built on: every header, row and empty line uses it so
 *  the four columns stay aligned. Actions get their own flexible track (and `truncate`
 *  inside the cell) — a fixed 140px clips real labels on a wide window. */
export const ROW_GRID =
  'grid grid-cols-[minmax(0,1fr)_minmax(140px,0.9fr)_150px_120px] gap-4 items-center px-4';
