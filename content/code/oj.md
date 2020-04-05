Title: Happy Onlie Judge
Date: 2019-9-29 13:00
Modified: 2019-9-29 13:00
Status: draft
Tags: online judge
Slug: oj
Authors: Yori Fang
Summary: Happy Coding

### Word Maze 

This is from http://happyoj.com/contest/2/problem/C

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

#define MAX_COL 100
#define MAX_ROW  20

bool is_maze(char words[][MAX_COL], int i, int j, int row, int col, char *target, int len) {
    if (len == 0)
        return true;

    if (i >= row || j >= col || i < 0 || j < 0)
        return false;

    bool match = false;
    char x = words[i][j];
    if (x == *target) {
        words[i][j] = '\0';
        match = is_maze(words, i - 1, j, row, col, target + 1, len - 1) ||
                is_maze(words, i + 1, j, row, col, target + 1, len - 1) ||
                is_maze(words, i, j - 1, row, col, target + 1, len - 1) ||
                is_maze(words, i, j + 1, row, col, target + 1, len - 1);
        words[i][j] = x;
    }

    return match;
}

bool word_maze(char words[][MAX_COL], int row, int col, char *target, int len) {
    if (len == 0)
        return true;

    for (int i = 0; i < row; i++) {
        for (int j = 0; j < col; j++) {
            if (words[i][j] == target[0]) {
                if (is_maze(words, i, j, row, col, target, len)) {
                    return true;
                }
            }
        }
    }
    return false;
}


int main() {
    int row, col;

    char target[MAX_COL] = {0};
    char words[MAX_ROW][MAX_COL] = {0};

    scanf("%d %d\n", &row, &col);
    scanf("%s", &target);

    for (int i = 0; i < row; i++) {
        scanf("%s", words[i]);
    }

    bool ret = word_maze(words, row, col, target, strlen(target));
    if (ret) {
        printf("YES\n");
    } else {
        printf("NO\n");
    }

    return 0;
}
```

## Matrix Max Sum Path
Dynamic Programing Algorithm

https://blog.csdn.net/sinat_35261315/article/details/78594116
```c
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>

#define MAX_SIZE 100

int get_max(int a, int b) {
    return a > b ? a : b;
}

int find_max(int matrix[][MAX_SIZE], int row, int col) {

    int dp[MAX_SIZE][MAX_SIZE] = {0};

    for (int i = 0; i < row; i++) {
        for (int j = 0; j < col; j++) {
            if (i == 0 && j >= 1) {
                dp[i][j] = dp[i][j - 1] + matrix[i][j];
            } else if (i >= 1 && j == 0) {
                dp[i][j] = dp[i - 1][j] + matrix[i][j];
            } else if (i - 1 >= 0 && j - 1 >= 0) {
                dp[i][j] = get_max(dp[i - 1][j], dp[i][j - 1]) + matrix[i][j];
            } else {
                dp[i][j] += matrix[i][j];
            }
        }
    }

    return dp[row - 1][col - 1];
}


int main() {
    int row, col;
    int matrix[MAX_SIZE][MAX_SIZE] = {0};


    scanf("%d %d", &row, &col);

    for (int i = 0; i < row; i++) {
        for (int j = 0; j < col; j++) {
            scanf("%d", &matrix[i][j]);
        }
    }

    int max = find_max(matrix, row, col);
    printf("%d\n", max);
}
```
Solution for Uniq Paths
https://leetcode.com/problems/unique-paths/
```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX 100

int get_step(int m, int n) {
    int dp[MAX][MAX] = {0};

    for (int i = 0; i < m; i++) {
        for (int j = 0; j < n; j++) {
            if (i == 0) {
                dp[0][j] = 1;
            } else if (j == 0) {
                dp[i][0] = 1;
            } else {
                dp[i][j] = dp[i - 1][j] + dp[i][j - 1];
            }
        }
    }

    return dp[m - 1][n - 1];
}

int main() {
    int m, n;
    scanf("%d %d", &m, &n);

    printf("%d\n", get_step(m, n));
}
```
