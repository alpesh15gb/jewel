from jewel_server.main import app, cli
from jewel_server.rate_management import install as install_rate_management

install_rate_management(app)

if __name__ == "__main__":
    cli()
