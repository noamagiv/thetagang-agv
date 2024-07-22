- Main -> Thetagang.start()
    1. normalize_config()
    2. validate_config()
    3. draw configuration - not in function
    4. PortfolioManager.init()
    5. IB.init()
    6. ib.connect()
    * on connect event -> portfolio_manager.manage()

- On Connect Event -> portfolio_manager.manage()
    1. self.initialize_account()
    2. summarize_account()
    3. chack_if_we_can_write_puts()
    4. check_for_uncovered_positions()

