package pkg

import "testing"

func TestCalc(t *testing.T) {
	if Calc(1, 2) != 3 {
		t.Fatal("Calc(1, 2) != 3")
	}
}
