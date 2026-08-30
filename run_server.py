import jewel_server.main as main_module
from jewel_server.rate_management import install_rate_management

install_rate_management(main_module)

if __name__ == "__main__":
    main_module.cli()
