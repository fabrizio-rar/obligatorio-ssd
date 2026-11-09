/**
 * Formatting and the i18n dictionary (docs/PLAN.md §13): categories, subcategories and stock states
 * are shown in Spanish; product names and spec values stay in their original language.
 * Unknown keys fall back to the original text, so a new dataset value never breaks the UI.
 */
import type { StockStatus } from '@/api/types'

const priceFormat = new Intl.NumberFormat('es-UY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** "366.38" → "USD 366,38". Prices come from the API as decimal strings. */
export function formatPrice(amount: string | number, currency = 'USD'): string {
  const value = typeof amount === 'number' ? amount : Number(amount)
  return `${currency} ${priceFormat.format(value)}`
}

const CATEGORIES: Record<string, string> = {
  Monitors: 'Monitores',
  Laptops: 'Notebooks',
  Headphones: 'Auriculares',
  Keyboards: 'Teclados',
  Mice: 'Mouses',
  Webcams: 'Cámaras web',
  'Docking Stations': 'Docks y hubs',
  'External Storage': 'Almacenamiento externo',
  Routers: 'Routers',
  Speakers: 'Parlantes',
  Printers: 'Impresoras',
  Tablets: 'Tablets',
}

const SUBCATEGORIES: Record<string, string> = {
  Office: 'Oficina',
  Professional: 'Profesional',
  Business: 'Empresarial',
  Creator: 'Creadores',
  'On-Ear': 'Supraaurales',
  'Over-Ear': 'Circumaurales',
  'True Wireless': 'Inalámbricos (TWS)',
  Mechanical: 'Mecánicos',
  'Low Profile': 'Perfil bajo',
  Ergonomic: 'Ergonómicos',
  Productivity: 'Productividad',
  Standard: 'Estándar',
  Conference: 'Conferencias',
  Universal: 'Universales',
  'Portable SSD': 'SSD portátil',
  'Desktop SSD': 'SSD de escritorio',
  'Rugged SSD': 'SSD resistente',
  Desktop: 'De escritorio',
  Portable: 'Portátiles',
  'Laser Mono': 'Láser monocromo',
  'Laser Color': 'Láser color',
  Compact: 'Compactas',
}

// backend/app/retrieval/vocabulary_data/use_cases.json (closed list)
const USE_CASES: Record<string, string> = {
  backups: 'backups',
  calls: 'llamadas',
  commuting: 'traslados',
  'content creation': 'creación de contenido',
  'creative work': 'trabajo creativo',
  'desk audio': 'audio de escritorio',
  'desk setup': 'escritorio',
  documents: 'documentos',
  ergonomics: 'ergonomía',
  gaming: 'gaming',
  'home networking': 'red hogareña',
  'home office': 'home office',
  'hybrid work': 'trabajo híbrido',
  'laptop expansion': 'expandir la notebook',
  'large homes': 'casas grandes',
  media: 'multimedia',
  movies: 'películas',
  multitasking: 'multitarea',
  music: 'música',
  'note taking': 'tomar notas',
  'office work': 'trabajo de oficina',
  photos: 'fotos',
  'portable storage': 'almacenamiento portátil',
  productivity: 'productividad',
  programming: 'programación',
  'remote work': 'trabajo remoto',
  'small business': 'pequeñas empresas',
  sports: 'deporte',
  streaming: 'streaming',
  study: 'estudio',
  travel: 'viajes',
  typing: 'escritura',
  'video calls': 'videollamadas',
  'video editing': 'edición de video',
  'air travel': 'viajes en avión',
  'competitive gaming': 'gaming competitivo',
  'high-end gaming': 'gaming de alta gama',
  'photo printing': 'impresión de fotos',
  'shared quiet spaces': 'espacios compartidos silenciosos',
}

const SPEC_GROUPS: Record<string, string> = {
  General: 'General', // fixed rows of the comparison table
  Other: 'Otros',
  Accessories: 'Accesorios',
  Audio: 'Audio',
  Battery: 'Batería',
  Connectivity: 'Conectividad',
  Controls: 'Controles',
  Design: 'Diseño',
  Display: 'Pantalla',
  Durability: 'Durabilidad',
  Networking: 'Red',
  Performance: 'Rendimiento',
  Power: 'Energía',
  Printing: 'Impresión',
  Privacy: 'Privacidad',
  Scanning: 'Escaneo',
  Security: 'Seguridad',
  Software: 'Software',
  Storage: 'Almacenamiento',
  Typing: 'Escritura',
  Video: 'Video',
  Wired: 'Cableado',
  Wireless: 'Inalámbrico',
}

const STOCK_STATUS: Record<StockStatus, string> = {
  'In stock': 'En stock',
  'Low stock': 'Últimas unidades',
  'Out of stock': 'Sin stock',
}

export const translateCategory = (name: string) => CATEGORIES[name] ?? name
export const translateSubcategory = (name: string) => SUBCATEGORIES[name] ?? name
export const translateStockStatus = (status: StockStatus) => STOCK_STATUS[status] ?? status
export const translateUseCase = (useCase: string) => USE_CASES[useCase] ?? useCase
export const translateSpecGroup = (group: string) => SPEC_GROUPS[group] ?? group

const dateTimeFormat = new Intl.DateTimeFormat('es-UY', { dateStyle: 'medium', timeStyle: 'short' })

/** "9 nov 2026, 00:37" in the user's time zone (the API sends UTC). */
export const formatDateTime = (iso: string) => dateTimeFormat.format(new Date(iso))

export const PAYMENT_LABELS: Record<string, string> = {
  CARD: 'Tarjeta',
  BANK_TRANSFER: 'Transferencia bancaria',
  CASH_ON_PICKUP: 'Efectivo al retirar',
}

/** The 19 departments of Uruguay, for the shipping address. */
export const URUGUAY_DEPARTMENTS = [
  'Artigas',
  'Canelones',
  'Cerro Largo',
  'Colonia',
  'Durazno',
  'Flores',
  'Florida',
  'Lavalleja',
  'Maldonado',
  'Montevideo',
  'Paysandú',
  'Río Negro',
  'Rivera',
  'Rocha',
  'Salto',
  'San José',
  'Soriano',
  'Tacuarembó',
  'Treinta y Tres',
]
