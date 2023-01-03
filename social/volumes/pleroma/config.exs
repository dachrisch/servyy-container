import Config

config :shout, enabled: false

config :pleroma, :frontend_configurations,
  pleroma_fe: %{
    theme: "pleroma-light",
    redirectRootNoLogin: "/hello",
    background: '/bumble.social.background.png'
}

config :pleroma, :instance,
  static_dir: "/var/lib/pleroma/static/"
