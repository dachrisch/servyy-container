# pleroma-docker-compose

This repo can be used as an example of utilizing docker-compose for your pleroma instance. It will start a pleroma instance container and pleroma-db (postgres) container. The instance will be available on `127.0.0.1:4000` - you will need to provide your own proxy such as nginx. 

Please be advised you may need to adjust some things to fit your environment. 

To deploy a pleroma instance using docker-compose - perform the following:

```
# git clone https://git.pleroma.social/pleroma/pleroma-docker-compose.git
# cd pleroma-docker-compose
```

You will need to edit the `./environments/pleroma/pleroma.env` and replace the `ops.pleroma.social` domain with your own (and other necessary configuration variables you need)

After, start the containers with:

```
# docker-compuse up -d
```

After pleroma initializes it should be available to proxy to on port 4000. 

_Notes_

You can customize the mounted config.exs to extend the pleroma config outside the ones generated off environment variables

In `./volumes/pleroma/config.exs` you can append like so:

```
# cat volumes/pleroma/config.exs
import Config

config :pleroma, :instance,
  registrations_open: true,
  federating: true
```

The postgres database files are located in `./volumes/pleroma-db/pgdata`. You can also insert postgres startup scripts inside `./volumes/pleroma-db/pginit`

