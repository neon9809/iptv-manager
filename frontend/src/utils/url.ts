export function sanitizeUrl(url: string | undefined): string {
  if (!url) return ''
  try {
    const urlObj = new URL(url)
    let path = urlObj.pathname
    
    const segments = path.split('/')
    if (segments.length > 2) {
      const filename = segments[segments.length - 1]
      if (filename) {
        const extParts = filename.split('.')
        const ext = extParts.length > 1 ? '.' + extParts.pop() : ''
        const basename = filename.substring(0, filename.length - ext.length)
        if (basename.length > 4) {
          segments[segments.length - 1] = basename.substring(0, 4) + '****' + ext
        }
        path = segments.join('/')
      }
    }
    
    return `${urlObj.protocol}//${urlObj.host}${path}`
  } catch {
    return url
  }
}
