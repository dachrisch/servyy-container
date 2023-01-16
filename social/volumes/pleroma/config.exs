import Config

config :shout, enabled: false

config :pleroma, :frontend_configurations,
  pleroma_fe: %{
    theme: "pleroma-light",
    redirectRootNoLogin: "/hive",
    background: "/images/bumble.social.background.png",
    logo: "/static/logo.svg"
}

config :pleroma, :instance,
  static_dir: "/var/lib/pleroma/static/"
