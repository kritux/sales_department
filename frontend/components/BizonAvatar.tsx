import Image from 'next/image'
import clsx from 'clsx'

export type BizonExpression =
  | 'default_smile'
  | 'wink_side_smile'
  | 'alert_wide_eyes'
  | 'happy_open_mouth'
  | 'surprised_o_mouth'
  | 'shocked_gasp'
  | 'skeptical_flat'
  | 'content_smile_teeth'
  | 'confused_tongue_out'
  | 'angry_frustrated'
  | 'sleepy_half_closed'
  | 'silly_tongue_wink'
  | 'scanning_spiral_eyes'
  | 'excited_sparkle_eyes'
  | 'calm_relaxed'
  | 'error_glitch_eyes'

const EXPRESSION_MAP: Record<BizonExpression, string> = {
  default_smile:       '/assets/bizon/bizon_01_default_smile.png',
  wink_side_smile:     '/assets/bizon/bizon_02_wink_side_smile.png',
  alert_wide_eyes:     '/assets/bizon/bizon_03_alert_wide_eyes.png',
  happy_open_mouth:    '/assets/bizon/bizon_04_happy_open_mouth.png',
  surprised_o_mouth:   '/assets/bizon/bizon_05_surprised_o_mouth.png',
  shocked_gasp:        '/assets/bizon/bizon_06_shocked_gasp.png',
  skeptical_flat:      '/assets/bizon/bizon_07_skeptical_flat.png',
  content_smile_teeth: '/assets/bizon/bizon_08_content_smile_teeth.png',
  confused_tongue_out: '/assets/bizon/bizon_09_confused_tongue_out.png',
  angry_frustrated:    '/assets/bizon/bizon_10_angry_frustrated.png',
  sleepy_half_closed:  '/assets/bizon/bizon_11_sleepy_half_closed.png',
  silly_tongue_wink:   '/assets/bizon/bizon_12_silly_tongue_wink.png',
  scanning_spiral_eyes:'/assets/bizon/bizon_13_scanning_spiral_eyes.png',
  excited_sparkle_eyes:'/assets/bizon/bizon_14_excited_sparkle_eyes.png',
  calm_relaxed:        '/assets/bizon/bizon_15_calm_relaxed.png',
  error_glitch_eyes:   '/assets/bizon/bizon_16_error_glitch_eyes.png',
}

interface BizonAvatarProps {
  expression?: BizonExpression
  size?: number
  rounded?: 'sm' | 'md' | 'lg' | 'full'
  className?: string
  alt?: string
  priority?: boolean
}

export default function BizonAvatar({
  expression = 'default_smile',
  size = 40,
  rounded = 'md',
  className,
  alt,
  priority = false,
}: BizonAvatarProps) {
  const src = EXPRESSION_MAP[expression]
  const radiusMap = {
    sm: '4px',
    md: '8px',
    lg: '12px',
    full: '50%',
  }

  return (
    <div
      className={clsx('overflow-hidden flex-shrink-0', className)}
      style={{
        width: size,
        height: size,
        borderRadius: radiusMap[rounded],
      }}
    >
      <Image
        src={src}
        alt={alt ?? `Bizon — ${expression.replace(/_/g, ' ')}`}
        width={size}
        height={size}
        className="object-cover w-full h-full"
        priority={priority}
      />
    </div>
  )
}
