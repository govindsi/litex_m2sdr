BUILD_DIR ?=

OBJECTS = crt0.o main.o

ifeq ($(MAKECMDGOALS),clean)
clean:
	$(RM) $(OBJECTS) m2sdr_diag.elf m2sdr_diag.bin m2sdr_diag.elf.map .*~ *~

.PHONY: clean

else

ifeq ($(strip $(BUILD_DIR)),)
$(error BUILD_DIR is not set. Example: make BUILD_DIR=../../../../build/<your_build_name>)
endif

VAR_MAK := $(BUILD_DIR)/software/include/generated/variables.mak
ifeq ($(wildcard $(VAR_MAK)),)
$(error Invalid BUILD_DIR. Expected $(VAR_MAK) to exist. Point BUILD_DIR at your SoC build directory under litex_m2sdr/build/<build_name>)
endif

include $(VAR_MAK)
include $(SOC_DIRECTORY)/software/common.mak

all: m2sdr_diag.bin

%.bin: %.elf
	$(OBJCOPY) -O binary $< $@
ifneq ($(OS),Windows_NT)
	chmod -x $@
endif

vpath %.a $(PACKAGES:%=../%)

m2sdr_diag.elf: $(OBJECTS)
	$(CC) $(LDFLAGS) -T linker.ld -N -o $@ \
		$(OBJECTS) \
		$(PACKAGES:%=-L$(BUILD_DIR)/software/%) \
		-Wl,--whole-archive \
		-Wl,--gc-sections \
		-Wl,-Map,$@.map \
		$(LIBS:lib%=-l%)
ifneq ($(OS),Windows_NT)
	chmod -x $@
endif

-include $(OBJECTS:.o=.d)

VPATH = $(BIOS_DIRECTORY):$(BIOS_DIRECTORY)/cmds:$(CPU_DIRECTORY)

%.o: %.c
	$(compile)

%.o: %.S
	$(assemble)

.PHONY: all

endif

