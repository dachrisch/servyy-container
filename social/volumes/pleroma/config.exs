import Config

config :shout, enabled: false

config :pleroma, :frontend_configurations,
  pleroma_fe: %{
    theme: "pleroma-light",
    redirectRootNoLogin: "/hello",
    background: "/images/bumble.social.background.png",
    logo: "/static/logo.png"
}

config :pleroma, :instance,
  static_dir: "/var/lib/pleroma/static/"
