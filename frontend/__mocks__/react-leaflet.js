// react-leaflet stub — avoids Leaflet/window dependency in Jest
const React = require('react')

const stub = (name) => (props) => React.createElement('div', { 'data-testid': name })

module.exports = {
  MapContainer:      stub('MapContainer'),
  TileLayer:         stub('TileLayer'),
  Circle:            stub('Circle'),
  Marker:            stub('Marker'),
  Popup:             stub('Popup'),
  useMap:            () => null,
}
