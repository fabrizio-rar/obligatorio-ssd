import { XIcon } from 'lucide-react'
import { type KeyboardEvent, useState } from 'react'

import type { CatalogFilters } from '@/api/endpoints'
import type { Brand } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Change = Partial<Omit<CatalogFilters, 'category' | 'sort'>>

interface Props {
  filters: CatalogFilters
  brands: Brand[] | undefined
  onChange: (change: Change) => void
  onClear: () => void
}

/** "" → null; anything that is not a number ≥ 0 → undefined (invalid). */
function parsePrice(text: string): number | null | undefined {
  const trimmed = text.trim().replace(',', '.')
  if (trimmed === '') return null
  const value = Number(trimmed)
  return Number.isFinite(value) && value >= 0 ? value : undefined
}

/**
 * Brand, price range and "only with stock" (RF-01). The state lives in the URL (CatalogPage);
 * prices are applied on Enter or when the field loses focus, not on every keystroke.
 */
export function CatalogFiltersBar({ filters, brands, onChange, onClear }: Props) {
  // Remount the inputs when the URL changes (back button, "Limpiar"), so they show the applied values
  const priceKey = `${filters.minPrice}-${filters.maxPrice}`
  const active = filters.brand !== null || filters.minPrice !== null || filters.maxPrice !== null || filters.inStock

  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-3 rounded-xl border bg-card p-3 shadow-xs">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-brand">Marca</Label>
        <select
          id="filter-brand"
          className="h-8 min-w-40 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          value={filters.brand ?? ''}
          onChange={(e) => onChange({ brand: e.target.value || null })}
        >
          <option value="">Todas</option>
          {/* A brand from the URL that has no products in this category still shows as selected */}
          {filters.brand && brands && !brands.some((b) => b.name === filters.brand) && (
            <option value={filters.brand}>{filters.brand} (0)</option>
          )}
          {brands?.map((b) => (
            <option key={b.brand_id} value={b.name}>
              {b.name} ({b.product_count})
            </option>
          ))}
        </select>
      </div>

      <PriceRange key={priceKey} min={filters.minPrice} max={filters.maxPrice} onApply={onChange} />

      <label className="flex h-8 cursor-pointer items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4 accent-primary"
          checked={filters.inStock}
          onChange={(e) => onChange({ inStock: e.target.checked })}
        />
        Solo con stock
      </label>

      {active && (
        <Button variant="ghost" size="sm" onClick={onClear}>
          <XIcon data-icon="inline-start" />
          Limpiar filtros
        </Button>
      )}
    </div>
  )
}

function PriceRange({
  min,
  max,
  onApply,
}: {
  min: number | null
  max: number | null
  onApply: (change: Change) => void
}) {
  const [minText, setMinText] = useState(min === null ? '' : String(min))
  const [maxText, setMaxText] = useState(max === null ? '' : String(max))
  const [error, setError] = useState<string | null>(null)

  function apply() {
    const minPrice = parsePrice(minText)
    const maxPrice = parsePrice(maxText)
    if (minPrice === undefined || maxPrice === undefined) {
      setError('Ingresá un número mayor o igual a 0.')
      return
    }
    if (minPrice !== null && maxPrice !== null && minPrice > maxPrice) {
      setError('El mínimo no puede ser mayor que el máximo.')
      return
    }
    setError(null)
    if (minPrice !== min || maxPrice !== max) onApply({ minPrice, maxPrice })
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') apply()
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="filter-min-price">Precio (USD)</Label>
      <div className="flex items-center gap-2">
        <Input
          id="filter-min-price"
          inputMode="decimal"
          placeholder="Desde"
          aria-label="Precio desde"
          aria-invalid={error !== null}
          className="w-24"
          value={minText}
          onChange={(e) => setMinText(e.target.value)}
          onBlur={apply}
          onKeyDown={onKeyDown}
        />
        <span className="text-muted-foreground">–</span>
        <Input
          inputMode="decimal"
          placeholder="Hasta"
          aria-label="Precio hasta"
          aria-invalid={error !== null}
          className="w-24"
          value={maxText}
          onChange={(e) => setMaxText(e.target.value)}
          onBlur={apply}
          onKeyDown={onKeyDown}
        />
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
