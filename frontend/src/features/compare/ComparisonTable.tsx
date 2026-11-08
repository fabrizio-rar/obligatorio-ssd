import { Fragment } from 'react'
import { Link } from 'react-router-dom'

import type { Comparison, ComparisonRow } from '@/api/types'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ProductImage } from '@/features/catalog/ProductImage'
import { formatPrice, translateSpecGroup } from '@/lib/format'
import { cn } from '@/lib/utils'

// Fixed rows built by the backend (group "General"); spec attribute names stay in English
const GENERAL_LABELS: Record<string, string> = {
  Price: 'Precio',
  Discount: 'Descuento',
  Rating: 'Calificación',
  Stock: 'Stock disponible',
  Warranty: 'Garantía',
  'Return days': 'Días para devolver',
}

function label(row: ComparisonRow): string {
  return row.group === 'General' ? (GENERAL_LABELS[row.attribute] ?? row.attribute) : row.attribute
}

/** values[i] belongs to products[i]. The price is formatted from the structured field, not the text. */
function cell(comparison: Comparison, row: ComparisonRow, i: number): string {
  const value = row.values[i] ?? '—'
  if (row.group !== 'General') return value
  const product = comparison.products[i]
  if (row.attribute === 'Price' && product?.current_price && product.currency) {
    return formatPrice(product.current_price, product.currency)
  }
  return value.replace(/ months$/, ' meses').replace(/ reviews\)$/, ' reseñas)')
}

/**
 * Side-by-side table from GET /api/products/compare (RF-06). Rows grouped by spec group; the ones
 * where the products differ are highlighted. `compact` is the version that fits in the chat panel.
 */
export function ComparisonTable({
  comparison,
  onlyDifferences = false,
  compact = false,
}: {
  comparison: Comparison
  onlyDifferences?: boolean
  compact?: boolean
}) {
  const rows = onlyDifferences ? comparison.rows.filter((r) => r.differs) : comparison.rows
  const groups = new Map<string, ComparisonRow[]>()
  for (const row of rows) groups.set(row.group, [...(groups.get(row.group) ?? []), row])

  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No hay diferencias entre estos productos.</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border bg-background">
      <Table className={cn(compact && 'text-xs')}>
        <TableHeader>
          <TableRow>
            <TableHead className="sticky left-0 z-10 bg-background">{compact ? '' : 'Característica'}</TableHead>
            {comparison.products.map((p) => (
              <TableHead
                key={p.product_id}
                className={cn('h-auto py-2 align-bottom', compact ? 'min-w-24' : 'min-w-40')}
              >
                <Link to={`/products/${p.product_id}`} className="mb-1.5 block">
                  <ProductImage
                    src={p.image_url}
                    alt={p.name}
                    category={comparison.category}
                    className={cn('rounded-md', compact ? 'h-14 w-20' : 'aspect-[4/3] w-full max-w-48')}
                  />
                </Link>
                <Link
                  to={`/products/${p.product_id}`}
                  className="block whitespace-normal font-medium text-foreground hover:underline"
                >
                  {p.name}
                </Link>
                {!compact && p.brand && <span className="block font-normal text-muted-foreground">{p.brand}</span>}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...groups].map(([group, groupRows]) => (
            <Fragment key={group}>
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={comparison.products.length + 1}
                  className="bg-muted/50 py-1 text-xs font-medium text-muted-foreground uppercase"
                >
                  {translateSpecGroup(group)}
                </TableCell>
              </TableRow>
              {groupRows.map((row) => (
                <TableRow key={`${group}-${row.attribute}`}>
                  <TableCell className="sticky left-0 z-10 bg-background whitespace-normal text-muted-foreground">
                    {label(row)}
                  </TableCell>
                  {comparison.products.map((p, i) => (
                    <TableCell
                      key={p.product_id}
                      className={cn('whitespace-normal', row.differs ? 'font-medium' : 'text-muted-foreground')}
                    >
                      {cell(comparison, row, i)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </Fragment>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
