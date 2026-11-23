import QtQuick

// Descriptor logos are relative to the QML asset root. Remote and absolute
// URLs retain their meaning when a provider surface moves to another domain.
Image {
  property string logo: ""
  source: logo === "" ? "" : /^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(logo) ? logo : Qt.resolvedUrl("../../" + logo)
  fillMode: Image.PreserveAspectFit
  smooth: true
  cache: true
}
