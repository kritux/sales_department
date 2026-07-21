// Leaflet stub — avoids browser/window dependency in Jest
const L = {
  map: () => ({ addLayer: () => {}, remove: () => {}, setView: () => {} }),
  tileLayer: () => ({ addTo: () => {} }),
  circle: () => ({ addTo: () => {} }),
  marker: () => ({ addTo: () => {}, bindPopup: () => ({ addTo: () => {} }) }),
  divIcon: () => ({}),
  Icon: { Default: { prototype: {}, mergeOptions: () => {} } },
}
module.exports = L
module.exports.default = L
