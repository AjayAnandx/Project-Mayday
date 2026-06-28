import { useEffect, useRef } from 'react'
import { api } from '../services/api'

export function useLocation() {
  const sentRef = useRef(false)

  useEffect(() => {
    if (sentRef.current) return

    api.getLocation().then((loc) => {
      if (loc.lat !== null) {
        sentRef.current = true
        return
      }

      if (!navigator.geolocation) return

      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const { latitude, longitude } = pos.coords
          try {
            const res = await fetch(
              `https://geocoding-api.open-meteo.com/v1/search?name=${latitude},${longitude}&count=1&language=en&format=json`
            )
            const data = await res.json()
            const city = data.results?.[0]?.name || ''
            const country = data.results?.[0]?.country || ''
            await api.setLocation({ lat: latitude, lon: longitude, city, country })
          } catch {
            await api.setLocation({ lat: latitude, lon: longitude })
          }
          sentRef.current = true
        },
        () => { /* User denied — rely on IP fallback */ },
        { enableHighAccuracy: false, timeout: 10000 }
      )
    })
  }, [])
}
