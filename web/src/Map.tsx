import { lazy, Suspense, type ComponentProps } from 'react'

// MapLibre is most of the bundle; load it after the page so forms and text appear at once on slow phones.
const CaseMap = lazy(() => import('./CaseMap'))

export default function Map(props: ComponentProps<typeof CaseMap>) {
  const { height = '100%', label } = props
  return (
    <Suspense fallback={<div className="map map-loading" style={{ height }} role="region" aria-label={label ?? 'Map of the stream'} aria-busy="true" />}>
      <CaseMap {...props} />
    </Suspense>
  )
}
