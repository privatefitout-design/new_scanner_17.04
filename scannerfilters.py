def check_flat_base(data: dict, symbol: str) -> bool:
    """Простая заглушка. Потом сюда добавим настоящую логику flat base"""
    if not data:
        return False
    
    # Пока просто выводим данные для теста
    print(f"{symbol} | OI: {data['open_interest']:,.0f} | Price: {data['price']:.2f} | Vol: {data['volume']:,.0f}")
    
    # Здесь будет настоящая логика позже
    return False