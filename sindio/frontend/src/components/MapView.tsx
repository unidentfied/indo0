import { useEffect, useRef } from 'react'

export default function MapView() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number
    let t = 0

    const resize = () => {
      const parent = canvas.parentElement
      if (!parent) return
      canvas.width = parent.clientWidth
      canvas.height = parent.clientHeight
    }
    resize()
    window.addEventListener('resize', resize)

    const draw = () => {
      const w = canvas.width
      const h = canvas.height
      t += 0.005

      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--sindio-dark').trim()
      ctx.fillRect(0, 0, w, h)

      ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--sindio-border').trim()
      ctx.lineWidth = 1
      for (let i = 0; i < w; i += 40) {
        ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, h); ctx.stroke()
      }
      for (let i = 0; i < h; i += 40) {
        ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(w, i); ctx.stroke()
      }

      ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--sindio-muted').trim()
      ctx.lineWidth = 2
      ctx.beginPath(); ctx.moveTo(0, h * 0.3); ctx.bezierCurveTo(w * 0.3, h * 0.2, w * 0.6, h * 0.5, w, h * 0.4); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(w * 0.2, 0); ctx.bezierCurveTo(w * 0.3, h * 0.4, w * 0.5, h * 0.7, w * 0.4, h); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(w * 0.8, 0); ctx.bezierCurveTo(w * 0.7, h * 0.3, w * 0.6, h * 0.6, w * 0.9, h); ctx.stroke()

      const nodes = [
        { x: w * 0.3, y: h * 0.35, color: '#dc2626', label: 'Kilimani Grid: 88%' },
        { x: w * 0.65, y: h * 0.3, color: '#d97706', label: 'A8 Highway: Heavy' },
        { x: w * 0.5, y: h * 0.6, color: '#2563eb', label: 'Central Node' },
      ]

      nodes.forEach((node, i) => {
        const pulse = Math.sin(t * 2 + i) * 0.3 + 0.7
        const radius = 6 + pulse * 4
        const grad = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, radius * 3)
        grad.addColorStop(0, node.color + '40')
        grad.addColorStop(1, 'transparent')
        ctx.fillStyle = grad
        ctx.beginPath(); ctx.arc(node.x, node.y, radius * 3, 0, Math.PI * 2); ctx.fill()
        ctx.fillStyle = node.color
        ctx.beginPath(); ctx.arc(node.x, node.y, 5, 0, Math.PI * 2); ctx.fill()
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--sindio-text').trim()
        ctx.font = '11px Inter, -apple-system, sans-serif'
        ctx.fillText(node.label, node.x + 12, node.y + 4)
      })

      ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--sindio-accent').trim() + '20'
      ctx.lineWidth = 1
      for (let i = 0; i < 5; i++) {
        const offset = (t * 50 + i * 30) % w
        ctx.beginPath(); ctx.moveTo(offset, h * 0.3 + Math.sin(offset * 0.01) * 20)
        ctx.lineTo(offset + 10, h * 0.3 + Math.sin((offset + 10) * 0.01) * 20); ctx.stroke()
      }

      animationId = requestAnimationFrame(draw)
    }
    draw()
    return () => { window.removeEventListener('resize', resize); cancelAnimationFrame(animationId) }
  }, [])

  return (
    <div className="panel overflow-hidden relative">
      <div className="absolute top-3 left-3 z-10 flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
        <span className="text-xs text-sindio-muted font-medium">Active</span>
      </div>
      <canvas ref={canvasRef} className="w-full h-full min-h-[320px]" />
    </div>
  )
}
