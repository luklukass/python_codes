def levenshtein_distance(str1, str2):
    m = len(str1)
    n = len(str2)

    # Inicializace matice
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    # Počáteční hodnoty
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    # Vyplňování matice
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if str1[i - 1] == str2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]) + 1

    return dp[m][n]


# Příklad použití
str1 = "test"
str2 = "rest"
print(levenshtein_distance(str1, str2))